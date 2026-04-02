# Flashing Windows

When the specified ISO file is found to be a Windows ISO, many things are done to work around the quirks with Windows.

The steps are as follows:

1. Mount the ISO
2. Partition the drive the file is being flashed to
3. Format the partitions
4. Mount the partitions and copy the files of the ISO with [`shutil`](https://docs.python.org/3/library/shutil.html)
5. Copy the EFI boot files
6. Sync the writes to disk and unmount the partitions and ISO
