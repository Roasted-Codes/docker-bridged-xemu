#!/bin/bash
# Auto-join the Halo 2 MLG arena on startup
# This script runs before kaiengine via the ich777 custom script hook
sed -i 's|kaiengine --configfile|kaiengine --arena "Arena/XBox/First Person Shooter/Halo 2/North America/MLG" --configfile|' /opt/scripts/start-server.sh
echo "---Configured auto-join: Arena/XBox/First Person Shooter/Halo 2/North America/MLG---"
