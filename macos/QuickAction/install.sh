#!/bin/zsh
# Installs the Finder Quick Action: right-click PDFs → Quick Actions → Compress with PaperLite.
set -e
here=${0:A:h}
mkdir -p ~/Library/Services
rm -rf ~/Library/Services/"Compress with PaperLite.workflow"
cp -R "$here/Compress with PaperLite.workflow" ~/Library/Services/
/System/Library/CoreServices/pbs -update
echo "Installed. Right-click a PDF in Finder → Quick Actions → Compress with PaperLite."
