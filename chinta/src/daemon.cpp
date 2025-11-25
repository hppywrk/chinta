#include <iostream>
#include <fstream>
#include <unistd.h> // For fork, setsid, chdir, close
#include <syslog.h> // For syslog
#include <signal.h> // For signal

void signal_handler(int signum) {
    if (signum == SIGTERM || signum == SIGINT) {
        syslog(LOG_INFO, "Daemon received signal %d, exiting.", signum);
        closelog();
        exit(0);
    }
}

int main() {
    // Fork the process
    pid_t pid = fork();

    if (pid < 0) {
        // Fork failed
        exit(EXIT_FAILURE);
    }
    if (pid > 0) {
        // Parent process exits
        exit(EXIT_SUCCESS);
    }

    // Child process continues (becomes the daemon)

    // Create a new session
    if (setsid() < 0) {
        exit(EXIT_FAILURE);
    }

    // Change the current working directory to root
    if (chdir("/") < 0) {
        exit(EXIT_FAILURE);
    }

    // Close standard file descriptors (stdin, stdout, stderr)
    close(STDIN_FILENO);
    close(STDOUT_FILENO);
    close(STDERR_FILENO);

    // Open syslog for logging
    openlog("my_daemon", LOG_PID | LOG_NDELAY, LOG_DAEMON);
    syslog(LOG_INFO, "Daemon started.");

    // Register signal handlers for graceful shutdown
    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);

    // Main daemon loop
    while (true) {
        syslog(LOG_INFO, "Daemon is running...");
        // Perform daemon's tasks here
        sleep(5); // Sleep for 5 seconds
    }

    closelog();
    return 0;
}
