import pygal
import os,os.path

prefix=os.path.split(pygal.__file__)[0].replace("\\", "/")

hiddenimports = (['pygal.graph.'+os.path.splitext(x)[0] 
    for x in filter(lambda x: os.path.splitext(x)[1] == ".py" and x[0] != "_", 
                    os.listdir(prefix + "/graph"))] +
                ['pygal.css.'+os.path.splitext(x)[0] 
    for x in filter(lambda x: os.path.splitext(x)[1] == ".py" and x[0] != "_", 
                    os.listdir(prefix + "/css"))])

hiddenimports += ["xml", "xml.etree", "xml.etree.ElementTree"]

#datas = [(prefix+"/graph/*.svg", "pygal/graph"),
#         (prefix+"/css/*.css",   "pygal/css"),
#        ]
#print(datas)
print("pygal hook executed!")
