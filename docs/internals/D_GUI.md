# GUI

Lufus GUI is made using PyQt6 (which is quite similar to PySide6). All the buttons and windows are defined in that file. The various processes that run when an interaction is done with a component are also defined in that file. These processes are basically just calling various related functions in sequential order as they're supposed to be. Thus, a process in that file is made of other functions imported from the various different files located mainly in the drive folder. It especially uses the states file to transfer/share the data (i.e. an option) chosen by the user to an intermediary file which is further read by the backend files to determine the various commands that are to be run when a function is called in the GUI (like a complete cycle!).

For example, when the start button is run then the program determines what kind of image option and modes are selected by the user. If it is, for example, only formatting mode, then the program runs the sequence for that. The sequence involves unmounting the drive, performing the commands and then remounting the drive, this is done while also updating the progress bar. The commands are also determined by what the user has selected, if the user selected to format a drive to NTFS with label "VOL1" then those two are shared as a variable in states.py, which is then read by the backend file (here, formatting.py) which changes which commands are run and how, after which the gui calls that function from the file and the command is executed (here, the mkfs which formats a drive to NTFS and the change label command will be run).

All checkboxes and drop-down selection boxes are transferred to states file using index numbers. A checked box is 1 and an unchecked box is 0. If the first item in a drop down box is selected then 0 will be the index number, 1 for the second item, 2 for third item and so on.

By default the states file has the first index number selected by default in case the user starts without touching any of the options.

In a few exceptions, the state file has some other value assigned by default instead of the index number.
