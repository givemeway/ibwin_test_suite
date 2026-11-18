#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CHUNK_SIZE (4 * 1024 * 1024) // 4 MB buffer for fast disk writes
#define TARGET_SIZE (1LL * 1024 * 1024 * 1024) // 1 GB in bytes

int main() {
  FILE *fp = fopen("/home/sandeep/1GB_text_file.txt", "wb");
  if (!fp) {
    perror("Failed to open file for writing");
    return 1;
  }

  char *buffer = (char *)malloc(CHUNK_SIZE);
  if (!buffer) {
    perror("Memory allocation failed");
    fclose(fp);
    return 1;
  }

  long long total_written = 0;
  long long line_counter = 0;
  long long last_reported_gb = 0;
  time_t start_time = time(NULL);

  // Initial timestamp components
  int year = 2026, month = 6, day = 6, hour = 0, minute = 0, second = 0;

  printf("Starting generation of 100 GB unique text file...\n");

  while (total_written < TARGET_SIZE) {
    char *ptr = buffer;
    char *end = buffer + CHUNK_SIZE;

    // Fill the 4 MB buffer with uniquely formatted lines
    while (ptr < end) {
      int written_bytes =
          snprintf(ptr, end - ptr,
                   "%04d-%02d-%02d %02d:%02d:%02d [INFO] User session active - "
                   "transaction ID #%lld\n",
                   year, month, day, hour, minute, second, line_counter);

      // If the buffer doesn't have enough space left for the full line, break
      // and flush
      if (written_bytes >= end - ptr) {
        break;
      }

      ptr += written_bytes;
      line_counter++;

      // Increment time sequentially for realism
      second++;
      if (second >= 60) {
        second = 0;
        minute++;
      }
      if (minute >= 60) {
        minute = 0;
        hour++;
      }
      if (hour >= 24) {
        hour = 0;
        day++;
      }
    }

    size_t bytes_to_write = ptr - buffer;
    size_t written = fwrite(buffer, 1, bytes_to_write, fp);
    if (written != bytes_to_write) {
      perror("Write error (disk might be full)");
      break;
    }
    total_written += written;

    // Print progress every 10 GB
    long long current_gb = total_written / (1024 * 1024 * 1024);
    if (current_gb >= last_reported_gb + 10) {
      printf("Progress: %lld GB / 100 GB written (Lines generated: %lld)...\n",
             current_gb, line_counter);
      last_reported_gb = current_gb;
    }
  }

  free(buffer);
  fclose(fp);

  time_t end_time = time(NULL);
  printf("Successfully generated 100 GB unique text file in %ld seconds.\n",
         (long)(end_time - start_time));
  printf("Total unique lines written: %lld\n", line_counter);
  return 0;
}
