#!/bin/bash

# Check if the input file argument is provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 devices.txt"
  exit 1
fi

INPUT_FILE="$1"

# Verify that the file exists
if [ ! -f "$INPUT_FILE" ]; then
  echo "Error: File '$INPUT_FILE' not found."
  exit 1
fi

echo "Starting device ID processing from: $INPUT_FILE"
echo "--------------------------------------------------"

# Extract device_id values using sed
sed -n 's/.*device_id="\([^"]*\)".*/\1/p' "$INPUT_FILE" | while read -r dev_id; do
  if [ -n "$dev_id" ]; then
    # Add prefix '5c0b' and suffix '4b5z'
    modified_id="5c0b${dev_id}4b5z"

    echo "-> Processing device_id: $dev_id"
    echo "-> Modified ID: $modified_id"

    # Execute the idevsutil command
    /home/code/2026/tls-support/IDRIVE/CLIENT/idevsutil_no_tls \
      test6@evstlsserver.idrive.com::home/ \
      --password-file=1234 \
      --port=443 \
      --delete-items \
      --files-from=fl.txt \
      --device-id="$modified_id"

    echo "--------------------------------------------------"
  fi
done

echo "Finished processing all device IDs."
