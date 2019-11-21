#!/bin/bash

if [ -z "$ENDROID" ]; then
    # Try and work out the path based on location of this script
    # This assumes this script hasn't been moved out of the repo
    # Note: this might not work in all cases but this only going to be
    # used in the dev phase so good enough
    ENDROID="$( cd $( dirname "$0" ) && cd .. && pwd )"
fi

if [ -z "$ENDROID_PLUGINS" ]; then
    # Default to looking in ~/.endroid/plugins/ for plugins
    ENDROID_PLUGINS="${HOME}/.endroid/plugins"
fi

export PYTHONPATH="${ENDROID}/lib/wokkel-0.7.1-py2.7.egg":"${ENDROID}/src/":"${ENDROID_PLUGINS}":"${PYTHONPATH}" 
echo "Setting PYTHONPATH=${PYTHONPATH}"
ENDROID_VERSION_INFO="${ENDROID}/src/endroid/version_info.py"
# Generate the version information for debugging purposes
${ENDROID}/gen_version.sh
echo "Running endroid at ${ENDROID} with plugins at ${ENDROID_PLUGINS}"
python -m endroid "$@"
