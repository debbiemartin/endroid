#!/bin/bash

#
# This script generates version information for Endroid
#

ENDROID_VERSION_INFO="src/endroid/version_info.py"
CURRENT_LOCATION="$( cd $( dirname "$0" ) && pwd )"
echo "Generating version info from ${CURRENT_LOCATION} at ${CURRENT_LOCATION}/${ENDROID_VERSION_INFO}"
cd ${CURRENT_LOCATION} && bzr version-info --python > ${ENDROID_VERSION_INFO} && cd -
