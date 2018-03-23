# Denne kan kjøres fra Python-konsollet i QGIS 3 (26/1-2018)
# De to "task"ene kjøres i sekvens dersom det bare er en cpu tilgjengelig
# Kode henta fra youtube.com/watch?v=6DIAc6ATOh0, og modifisert

context=QgsProcessingContext()
context.setProject(QgsProject.instance())
alg=QgsApplication.processingRegistry().algorithmById('native:buffer')
#alg=QgsApplication.processingRegistry().algorithmById('qgis:buffer')

#[p.name() for p in alg.parameterDefinitions()]

#params={
#'INPUT': 'input',
#'DISTANCE': 100.0,
#'OUTPUT':'/home/havatv/test.shp'
#}
params={
'INPUT': '32_0214vegsituasjon_linje',
'DISTANCE': 100.0,
'OUTPUT':'/home/havatv/test.shp'
##'OUTPUT': 'memory:myLayerName'  # Kræsjer QGIS!
}

task = QgsProcessingAlgRunnerTask(alg,params,context)
QgsApplication.taskManager().addTask(task)

print('Buffer 1 startet')

params={
'INPUT': '32_0214bygg_p',
'DISTANCE': 70.0,
#'OUTPUT':'memory'  # Crashes QGIS!
# 'OUTPUT' is a featuresink or a file
'OUTPUT':'/home/havatv/test2.shp'
}
task = QgsProcessingAlgRunnerTask(alg,params,context)
QgsApplication.taskManager().addTask(task)

print('Buffer 2 startet')

