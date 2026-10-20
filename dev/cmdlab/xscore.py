"""X-ASR run directly with onnxruntime (dev only): the encoder once, greedy search, and the RNN-T log-likelihood of
any token sequence on the same encoder output, so a closed set of commands can be scored against the free decode."""
import numpy as np
import onnxruntime as ort

from common import XASR

BLANK = 0


def _session(path, threads):
    o = ort.SessionOptions()
    o.inter_op_num_threads = 1
    o.intra_op_num_threads = threads
    o.log_severity_level = 3
    return ort.InferenceSession(str(path), sess_options=o, providers=["CPUExecutionProvider"])


def fbank(samples: np.ndarray) -> np.ndarray:
    import kaldi_native_fbank as knf
    opts = knf.FbankOptions()
    opts.frame_opts.dither = 0
    opts.frame_opts.snip_edges = False
    opts.frame_opts.window_type = "povey"
    opts.frame_opts.samp_freq = 16000
    opts.mel_opts.num_bins = 80
    fb = knf.OnlineFbank(opts)
    fb.accept_waveform(16000, samples.tolist())
    fb.input_finished()
    feats = np.stack([fb.get_frame(i) for i in range(fb.num_frames_ready)]).astype(np.float32)
    t = feats.shape[0]
    rem = ((t - 7) // 2) % 8
    if rem:
        feats = np.pad(feats, ((0, (((t - 7) // 2) + 8 - rem) * 2 + 7 - t), (0, 0)))
    return np.ascontiguousarray(feats)


class XScorer:
    def __init__(self, threads: int = 2):
        self.enc = _session(XASR / "encoder-epoch-99-avg-1.int8.onnx", threads)
        self.dec = _session(XASR / "decoder-epoch-99-avg-1.onnx", 1)
        self.join = _session(XASR / "joiner-epoch-99-avg-1.int8.onnx", 1)
        self.ctx = self.dec.get_inputs()[0].shape[1]
        self.id2tok, self.tok2id = {}, {}
        for line in (XASR / "tokens.txt").read_text(encoding="utf-8").splitlines():
            t, i = line.rsplit(" ", 1)
            self.id2tok[int(i)] = t
            self.tok2id[t] = int(i)

    def encode(self, samples: np.ndarray) -> np.ndarray:
        x = fbank(samples)[None]
        out = self.enc.run(None, {self.enc.get_inputs()[0].name: x,
                                  self.enc.get_inputs()[1].name: np.array([x.shape[1]], np.int32)})
        return out[0][0]   # (T, D)

    def _decoder(self, contexts: list) -> np.ndarray:
        x = np.array(contexts, np.int32)
        return self.dec.run(None, {self.dec.get_inputs()[0].name: x})[0].reshape(len(contexts), -1)

    def _joiner(self, e: np.ndarray, d: np.ndarray) -> np.ndarray:
        logits = self.join.run(None, {self.join.get_inputs()[0].name: e.astype(np.float32),
                                      self.join.get_inputs()[1].name: d.astype(np.float32)})[0]
        m = logits.max(axis=-1, keepdims=True)
        return logits - m - np.log(np.exp(logits - m).sum(axis=-1, keepdims=True))

    def _context(self, hyp: list) -> list:
        h = [BLANK] * self.ctx + list(hyp)
        return h[-self.ctx:]

    def greedy(self, enc: np.ndarray) -> list:
        hyp = []
        d = self._decoder([self._context(hyp)])
        for t in range(enc.shape[0]):
            lp = self._joiner(enc[t:t + 1], d)[0]
            k = int(lp.argmax())
            if k != BLANK:
                hyp.append(k)
                d = self._decoder([self._context(hyp)])
        return hyp

    def logp(self, enc: np.ndarray, ids: list) -> float:
        """log P(ids | audio) summed over alignments, one symbol at most per frame (as the decoder searches)."""
        T, U = enc.shape[0], len(ids)
        if U > T:
            return -1e9
        d = self._decoder([self._context(ids[:u]) for u in range(U + 1)])          # (U+1, D)
        e = np.repeat(enc, U + 1, axis=0)
        dd = np.tile(d, (T, 1))
        lp = self._joiner(e, dd).reshape(T, U + 1, -1)
        blank = lp[:, :, BLANK]                                                     # (T, U+1)
        emit = np.stack([lp[:, u, ids[u]] for u in range(U)], axis=1) if U else np.zeros((T, 0))
        a = np.full(U + 1, -np.inf)
        a[0] = 0.0
        for t in range(T):
            nxt = a + blank[t]
            if U:
                nxt[1:] = np.logaddexp(nxt[1:], a[:-1] + emit[t])
            a = nxt
        return float(a[U])

    def ids(self, text: str) -> list | None:
        """Token ids of a Chinese phrase (characters as ▁X pieces, Simplified), None when one is missing."""
        from artvoiceinput.textfmt import to_simplified
        out = []
        for ch in to_simplified(text):
            k = self.tok2id.get("▁" + ch)
            if k is None:
                return None
            out.append(k)
        return out

    def text(self, ids: list) -> str:
        return "".join(self.id2tok[i] for i in ids).replace("▁", " ").strip()


def logp_many(self: XScorer, enc: np.ndarray, seqs: list) -> list:
    """logp for several token sequences on one encoder output, with one decoder and one joiner call."""
    T = enc.shape[0]
    rows, need = {}, []
    for ids in seqs:
        r = []
        for u in range(len(ids) + 1):
            c = tuple(self._context(ids[:u]))
            r.append(rows.setdefault(c, len(rows)))
        need.append(r)
    d = self._decoder([list(c) for c in rows])                       # (C, D)
    C = d.shape[0]
    lp = self._joiner(np.repeat(enc, C, axis=0), np.tile(d, (T, 1))).reshape(T, C, -1)
    out = []
    for ids, r in zip(seqs, need):
        U = len(ids)
        if U > T:
            out.append(-1e9)
            continue
        blank = lp[:, r, BLANK]                                       # (T, U+1)
        emit = lp[:, r[:-1], ids] if U else np.zeros((T, 0))           # (T, U)
        a = np.full(U + 1, -np.inf)
        a[0] = 0.0
        for t in range(T):
            nxt = a + blank[t]
            if U:
                nxt[1:] = np.logaddexp(nxt[1:], a[:-1] + emit[t])
            a = nxt
        out.append(float(a[U]))
    return out


XScorer.logp_many = logp_many


def score_commands(self: XScorer, enc: np.ndarray, seqs: list, owner: list, keep: float = -8.0):
    """Method A as the app would run it: commands whose first character is unlikely anywhere (log-prob below
    `keep` at every frame, from the start context) are not scored. -> {command: logp}"""
    d0 = self._decoder([self._context([])])
    first = self._joiner(enc, np.repeat(d0, enc.shape[0], axis=0)).max(axis=0)       # (V,)
    pick = [k for k, s in enumerate(seqs) if first[s[0]] >= keep]
    out = {}
    if pick:
        for k, v in zip(pick, self.logp_many(enc, [seqs[k] for k in pick])):
            out[owner[k]] = max(out.get(owner[k], -1e9), v)
    return out


XScorer.score_commands = score_commands
