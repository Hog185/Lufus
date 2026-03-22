# v---------------------- CHANGABLE SECTION ------------------------------v
# UPDATE THE THINGS IN THIS AREA ACCORDING TO THE DISTRO YOU CHOOSE.
# THIS IS TO MAKE SURE THAT YOUR DISTRO IS UPDATED AND IS READY TO INSTALL WITH THE CORRECT INSTALLATION SYNTAX
# USE THE REFERENCE BELOW (THIS IS FOR THE DEBIAN:LATEST):
apt-get update && apt-get upgrade
INSTALLER="apt-get install -y"
# ^---------------------- CHANGABLE SECTION ------------------------------^
# CONCRETE SECTION BELOW, DO NOT MODIFY THE STUFF BELOW THIS!
echo "------------ ENTERED LIBRARIES INSTALLATION SETUP ------------"
echo "appimage-setup-installer.sh is running..."
if [[ -f requirements-system.txt ]]; then
    if $INSTALLER $(cat requirements-system.txt) >> appimage-setup.log; then
        echo "INSTALLATION OF THE LIBRARIES IS COMPLETED!"
        echo "----------- EXITING LIBRARIES INSTALLATION SETUP -----------"
    else
        echo "THE INSTALLER DIDN'T WORKED, CHECK THE 4TH LINE OF THE appimage-setup-installer.sh."
        echo "Make sure it matches the distro you choose earlier on for the docker image."
    fi
else
    echo "requirements-system.txt NOT FOUND, WRITE IT IN THE ROOT DIRECTORY OF THE PROJECT >:3"
fi


