# Command-recognition lab (dev only)

Measures how well spoken commands said alone are recognized, on the user's saved recordings
(`%LOCALAPPDATA%\VoiceInput\recordings`, read only). Needs `onnxruntime`, `kaldi-native-fbank` and `soundfile`
besides the app's packages: use a separate venv with a `.pth` pointing at `.venv\Lib\site-packages` and the repo.
Output goes to `CMDLAB_OUT` (default `dev/cmdlab/out`); keyword-spotter models to `CMDLAB_KWS` (short paths:
sherpa-onnx fails beyond 260 characters).

1. `build.py`: samples (commands the app ran, VAD pieces of text utterances, short utterances to review).
2. `evaluate.py`: the app's current path and method A (`xscore.py`: X-ASR in onnxruntime, RNN-T score of each command).
3. `kws_eval.py zhen`: method B (sherpa-onnx keyword spotter).
4. `analyze.py`: every method's hits / misses / false triggers, and `queue.jsonl` to label with `label.py`.
5. `bench.py`, `boost_first.py`, `boost_score.py`, `pad_test.py`, `vad_test.py`: speed and accuracy ideas.

Findings (2026-10-17, continuous listening: 929 commands, 571 text pieces, labels by the user): see AGENTS.md.
