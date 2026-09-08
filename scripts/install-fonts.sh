#!/bin/bash
set -e

echo "Setting up Microsoft & custom fonts for LibreOffice..."

mkdir -p /usr/local/share/fonts/truetype/microsoft
mkdir -p /usr/local/share/fonts/truetype/custom
mkdir -p /etc/libreoffice/registry

# Download and extract Microsoft PowerPoint Viewer fonts if not present
if [ ! -f /usr/local/share/fonts/truetype/microsoft/calibri.ttf ]; then
  cd /tmp
  curl -sSL -o ppviewer.exe "https://archive.org/download/PowerPointViewer_201801/PowerPointViewer.exe" || true
  if [ -f ppviewer.exe ]; then
    cabextract -q ppviewer.exe || true
    if [ -f ppviewer.cab ]; then
      cabextract -q -d /usr/local/share/fonts/truetype/microsoft ppviewer.cab "*.TTF" "*.TTC" "*.ttf" "*.ttc" || true
    fi
    rm -f ppviewer.exe ppviewer.cab
  fi
fi

# Download Segoe UI family
cd /usr/local/share/fonts/truetype/microsoft
for f in segoeui.ttf segoeuib.ttf segoeuii.ttf segoeuiz.ttf seguisb.ttf; do
  if [ ! -f "$f" ]; then
    curl -sSL "https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/$f" -o "$f" || true
  fi
done

# Download Tahoma and Georgia
for f in Tahoma.ttf tahomabd.ttf Georgia.ttf georgiab.ttf georgiai.ttf georgiaz.ttf; do
  if [ ! -f "$f" ]; then
    curl -sSL "https://raw.githubusercontent.com/adrienverge/copr-some-nice-fonts/master/$f" -o "$f" || true
  fi
done

# Download Aptos fonts
cd /usr/local/share/fonts/truetype/custom
for f in "Aptos.ttf" "Aptos-Bold.ttf" "Aptos-Italic.ttf" "Aptos Display.ttf" "Aptos Display-Bold.ttf"; do
  if [ ! -f "$f" ]; then
    curl -sSL "https://raw.githubusercontent.com/thepbone/aptos-font/main/fonts/ttf/$f" -o "$f" || true
  fi
done

# Download Jameel Noori Nastaleeq for Urdu
if [ ! -f "Jameel Noori Nastaleeq.ttf" ]; then
  curl -sSL "https://raw.githubusercontent.com/urdufonts/urdufonts.github.io/master/fonts/Jameel%20Noori%20Nastaleeq.ttf" -o "Jameel Noori Nastaleeq.ttf" || true
fi

# Register font configuration
mkdir -p /etc/fonts/conf.d
cat << 'EOF' > /etc/fonts/conf.d/99-mjpdf-ms-aliases.conf
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <alias><family>Calibri</family><prefer><family>Calibri</family><family>Carlito</family></prefer></alias>
  <alias><family>Calibri Light</family><prefer><family>Calibri</family><family>Carlito</family></prefer></alias>
  <alias><family>Cambria</family><prefer><family>Cambria</family><family>Caladea</family></prefer></alias>
  <alias><family>Cambria Math</family><prefer><family>Cambria Math</family><family>Caladea</family></prefer></alias>
  <alias><family>Aptos</family><prefer><family>Aptos</family><family>Aptos Display</family><family>Carlito</family></prefer></alias>
  <alias><family>Aptos Display</family><prefer><family>Aptos Display</family><family>Carlito</family></prefer></alias>
  <alias><family>Segoe UI</family><prefer><family>Segoe UI</family><family>Carlito</family></prefer></alias>
  <alias><family>Tahoma</family><prefer><family>Tahoma</family><family>Liberation Sans</family></prefer></alias>
  <alias><family>Georgia</family><prefer><family>Georgia</family><family>Noto Serif</family></prefer></alias>
  <alias><family>Consolas</family><prefer><family>Consolas</family><family>Liberation Mono</family></prefer></alias>
  <alias><family>Arial</family><prefer><family>Arial</family><family>Liberation Sans</family></prefer></alias>
  <alias><family>Times New Roman</family><prefer><family>Times New Roman</family><family>Liberation Serif</family></prefer></alias>
  <alias><family>Courier New</family><prefer><family>Courier New</family><family>Liberation Mono</family></prefer></alias>
  <alias><family>Jameel Noori Nastaleeq</family><prefer><family>Jameel Noori Nastaleeq</family><family>Noto Nastaliq Urdu</family></prefer></alias>
</fontconfig>
EOF

# LibreOffice global compatibility definition
cat << 'EOF' > /etc/libreoffice/registry/msword_compatibility.xcd
<?xml version="1.0"?>
<oor:data xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:oor="http://openoffice.org/2001/registry">
  <dependency file="main"/>
  <dependency file="writer"/>
  <oor:component-data oor:name="Common" oor:package="org.openoffice.Office">
    <node oor:name="I18N">
      <node oor:name="CTL">
        <prop oor:name="CTLFont"><value>true</value></prop>
        <prop oor:name="CTLSequenceChecking"><value>true</value></prop>
      </node>
    </node>
  </oor:component-data>
  <oor:component-data oor:name="Compatibility" oor:package="org.openoffice.Office">
    <node oor:name="AllFileFormats">
      <prop oor:name="UsePrinterMetrics"><value>false</value></prop>
      <prop oor:name="AddSpacing"><value>false</value></prop>
      <prop oor:name="AddSpacingAtPages"><value>false</value></prop>
      <prop oor:name="UseOurTabStopFormat"><value>false</value></prop>
      <prop oor:name="NoExternalLeading"><value>true</value></prop>
      <prop oor:name="UseLineSpacing"><value>false</value></prop>
      <prop oor:name="AddTableSpacing"><value>false</value></prop>
      <prop oor:name="AddTableLineSpacing"><value>false</value></prop>
      <prop oor:name="UseOurTextWrapping"><value>false</value></prop>
      <prop oor:name="ConsiderWrappingStyle"><value>true</value></prop>
      <prop oor:name="ExpandWordSpace"><value>true</value></prop>
    </node>
  </oor:component-data>
</oor:data>
EOF

fc-cache -fv
echo "Fonts and LibreOffice MS Word compatibility successfully configured!"
