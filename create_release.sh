
echo Setting environment
export PYTHONPATH=$PWD:$PWD/stracker/externals

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

exit 0
