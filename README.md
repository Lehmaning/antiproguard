# deobfuspyor is a WIP Name. Will change before Release!

## Setup

* Clone this repo
* Requires python >= 3.4 and java >= 7 to be installed.
* Either do the following steps manually, or run `python init.py` and do the interactive initialization tool
* run `pip install -r requirements.txt` to get the required python modules
* It's preferred to do this in a virtualenv, see the documentation of virtualenv for this
* Download apktool (https://ibotpeaches.github.io/Apktool/), no need for the windows wrapper, store it somewhere and remember the location
* Download baksmali (https://bitbucket.org/JesusFreke/smali/downloads), store it somewhere and remember the location
* copy the config.example.py to config.py and edit the lines (especially database, apktool and baksmali locations)
* if you want to use _mysql_, set up a mysql database
* if you want to use _sqlite_, in the config file, comment out the mysql engine_url and remove the comment in front of the sqlite engine_url. Also, set mysql = True to False
* after setting up the database and editing the config, run `python apkdb.py`, it'll automatically create all tables needed
* You may have to create a folder called "decompiled" in the root folder of this application

## Usage

The main script to run is deobfuspyor.py
### Basic usage guide:

* If you want to add a jar/dex file to the database, run `python deobfuspyor.py -i <file.jar/file.dex>` (this requires the android SDK to be installed)
* If you want to add a whole, unobfuscated apk to the database, run `python deobfuspyor.py -sb -t <file.apk>`
* If you want to deobfuscate an apk, run `python deobfuspyor.py -d <file.apk>` The result is called "[file_name].deobfuscated.apk"

### Additional parameters:

* -t to time an operation
* -s to skip building and decompiling, -sb to only skip building, -sd to skip decompilation
* -k to keep the files after everything's done. Will remove decompiled files otherwise
