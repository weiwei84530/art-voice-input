// Art VoiceInput.app's executable: a small launcher that starts the real app (PyInstaller, in
// ~/Library/Application Support/ArtVoiceInput/app) as its child and lives as long as it does.
//
// Why: macOS gives the microphone, Accessibility and Input Monitoring to the app a process belongs to, a child
// counting as its parent app's, and remembers the permission by the app's code signature. Without an Apple
// Developer ID the signature is ad hoc, a hash of the files: the real app changes at every update, this launcher
// never does (built once, committed), so the user allows them once and updates keep them.
//
// Opened again while running (the Dock, Finder, Spotlight: macOS activates the running launcher instead of starting
// a new one), it starts the real app once more with no arguments, which asks the running one to show its settings
// window and quits. The child learns this bundle's path from ARTVOICEINPUT_APP (autostart and restart go through
// `open -a` with it).
//
//   clang -fobjc-arc -O2 -mmacosx-version-min=11.0 -arch x86_64 -arch arm64 -framework Cocoa launcher.m -o ArtVoiceInput
#import <Cocoa/Cocoa.h>
#include <spawn.h>
#include <sys/wait.h>

extern char **environ;

static NSString *AppExecutable(void) {
    NSString *support = [NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES)
                         firstObject];
    return [support stringByAppendingPathComponent:@"ArtVoiceInput/app/ArtVoiceInput"];
}

static pid_t Spawn(NSArray<NSString *> *args) {
    NSString *exe = AppExecutable();
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:exe]) {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"找不到阿特語音輸入法的程式檔案";
        alert.informativeText = @"請重新執行安裝程式。";
        [NSApp activateIgnoringOtherApps:YES];
        [alert runModal];
        return -1;
    }
    setenv("ARTVOICEINPUT_APP", [[[NSBundle mainBundle] bundlePath] fileSystemRepresentation], 1);
    NSUInteger n = args.count;
    char **argv = calloc(n + 2, sizeof(char *));
    argv[0] = strdup([exe fileSystemRepresentation]);
    for (NSUInteger i = 0; i < n; i++) argv[i + 1] = strdup([args[i] UTF8String]);
    pid_t pid = -1;
    int err = posix_spawn(&pid, argv[0], NULL, NULL, argv, environ);
    for (NSUInteger i = 0; i <= n; i++) free(argv[i]);
    free(argv);
    return err == 0 ? pid : -1;
}

@interface Launcher : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) dispatch_source_t exitWatch;
@end

@implementation Launcher

- (void)applicationDidFinishLaunching:(NSNotification *)note {
    NSArray<NSString *> *all = [[NSProcessInfo processInfo] arguments];
    NSMutableArray<NSString *> *args = [NSMutableArray array];
    for (NSUInteger i = 1; i < all.count; i++) {
        if (![all[i] hasPrefix:@"-psn_"]) [args addObject:all[i]];   // old macOS adds a process serial number
    }
    pid_t pid = Spawn(args);
    if (pid <= 0) {
        [NSApp terminate:nil];
        return;
    }
    // quit with the real app
    self.exitWatch = dispatch_source_create(DISPATCH_SOURCE_TYPE_PROC, (uintptr_t)pid, DISPATCH_PROC_EXIT,
                                            dispatch_get_main_queue());
    dispatch_source_set_event_handler(self.exitWatch, ^{
        int status = 0;
        waitpid(pid, &status, 0);
        [NSApp terminate:nil];
    });
    dispatch_resume(self.exitWatch);
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
    pid_t pid = Spawn(@[]);   // asks the running one to show its settings window, then quits
    if (pid > 0) {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            int status = 0;
            waitpid(pid, &status, 0);
        });
    }
    return NO;
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *app = [NSApplication sharedApplication];
        Launcher *delegate = [[Launcher alloc] init];
        app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyProhibited];   // no Dock icon, no menu of its own
        [app run];
    }
    return 0;
}
