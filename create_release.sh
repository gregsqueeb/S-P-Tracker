#!/bin/sh

echo Make sure that everything is checked in before proceeding

echo Setting environment
export PATH=/home/neys/local_sw/subersion-1.7.20/bin:/home/neys/local_sw/python33/bin:$PATH
export LD_LIBRARY_PATH=/home/neys/local_sw/subersion-1.7.20/lib:/home/neys/local_sw/python33/lib:/home/neys/local_sw/sqlite3_08_11_1/lib
export PYTHONPATH=$PWD:$PWD/stracker/externals

echo Switching svn to $1 ...
/home/neys/local_sw/subersion-1.7.20/bin/svn switch "$1"
echo Updating svn ...
/home/neys/local_sw/subersion-1.7.20/bin/svn update
if test "$(/home/neys/local_sw/subersion-1.7.20/bin/svn status -q | grep '^[AM] ')" == ""; then
	(
	  echo Cleaning up old version
	  cd stracker
	  rm -f stracker_linux_x86.tgz
	  rm -rf dist
	  rm -rf build
	  pyinstaller --clean -y -s --exclude-module http_templates --hidden-import cherrypy.wsgiserver.wsgiserver3 --hidden-import psycopg2 --additional-hooks-dir=$PWD/pyinstaller-hooks/ stracker.py

	  mv dist/stracker dist/stracker_linux_x86
	  tar cvzf stracker_linux_x86.tgz -C dist stracker_linux_x86
	  rm -rf dist
	  rm -rf build
      )

else
	echo svn copy is dirty. Please clean up your changes.
	exit 1
fi
exit 0
