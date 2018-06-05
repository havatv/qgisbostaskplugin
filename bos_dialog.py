# -*- coding: utf-8 -*-
"""
/***************************************************************************
 BOSDialog
                                 A QGIS plugin
 Implements the BOS method for assessing the accuracy of geographical lines
                             -------------------
        begin                : 2017-10-19
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Håvard Tveite
        email                : havard.tveite@nmbu.no
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from os.path import dirname
from os.path import join
#import os
import csv

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication, QObject, QThread
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.PyQt.QtWidgets import QPushButton, QProgressBar, QMessageBox
from qgis.PyQt.QtCore import Qt, QVariant

from qgis.PyQt.QtCore import QPointF, QLineF, QRectF, QPoint

from qgis.PyQt.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsLineItem, QGraphicsEllipseItem, QGraphicsTextItem
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtGui import QBrush, QPen, QColor
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtPrintSupport import QPrinter




#from qgis.core import QgsFeatureRequest, QgsField, QgsGeometry
from qgis.core import QgsField
from qgis.core import QgsProcessingAlgRunnerTask   # ok
from qgis.core import QgsApplication   # ok
from qgis.core import QgsProcessingContext  # thread manipulation?
from qgis.core import QgsProcessingFeedback
from qgis.core import QgsProcessingUtils

from qgis.core import Qgis

from qgis.core import QgsMessageLog, QgsProject

#from sys.path import append
#append(dirname(__file__))
#from processing.core.Processing import processing
import processing
from processing.tools import dataobjects


FORM_CLASS, _ = uic.loadUiType(join(
    dirname(__file__), 'bos_dialog_base.ui'))


class BOSDialog(QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        """Constructor."""
        self.iface = iface
        super(BOSDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)


        # Some constants for translated text
        self.BOS = self.tr('BOS')
        self.BROWSE = self.tr('Browse')
        self.CANCEL = self.tr('Cancel')
        self.HELP = self.tr('Help')
        self.CLOSE = self.tr('Close')
        self.OK = self.tr('OK')
        #self.NUMBEROFSTEPS = 10  # Number of steps

        okButton = self.button_box.button(QDialogButtonBox.Ok)
        okButton.setText(self.OK)
        cancelButton = self.button_box.button(QDialogButtonBox.Cancel)
        cancelButton.setText(self.CANCEL)
        helpButton = self.helpButton
        helpButton.setText(self.HELP)
        self.BOSscene = QGraphicsScene(self)
        self.BOSGraphicsView.setScene(self.BOSscene)

        # Connect signals
        okButton.clicked.connect(self.startWorker)

    def startWorker(self):
        """Initialises and starts."""
        try:
            statistics = []
            layerindex = self.inputLayer.currentIndex()
            layerId = self.inputLayer.itemData(layerindex)
            #2# inputlayer = QgsMapLayerRegistry.instance().mapLayer(layerId)
            inputlayer = QgsProject.instance().mapLayer(layerId)
            if inputlayer is None:
                self.showError(self.tr('No input layer defined'))
                return
            refindex = self.referenceLayer.currentIndex()
            reflayerId = self.referenceLayer.itemData(refindex)
            #2# reflayer = QgsMapLayerRegistry.instance().mapLayer(reflayerId)
            reflayer = QgsProject.instance().mapLayer(reflayerId)
            # not meaningful to 
            if layerId == reflayerId:
                self.showInfo('The reference layer must be different'
                              ' from the input layer!')
                return

            if reflayer is None:
                self.showError(self.tr('No reference layer defined'))
                return
            #if reflayer is not None and reflayer.crs().geographicFlag():
            if reflayer is not None and reflayer.sourceCrs().isGeographic():
                self.showWarning('Geographic CRS used for the reference layer -'
                                 ' computations will be in decimal degrees!')
            #outputlayername = self.outputDataset.text()
            #approximateinputgeom = self.approximate_input_geom_cb.isChecked()
            #joinprefix = self.joinPrefix.text()
            #useindex = True
            #useindex = self.use_index_nonpoint_cb.isChecked()
            #useindexapproximation = self.use_indexapprox_cb.isChecked()
            #distancefieldname = self.distancefieldname.text()
            steps = self.stepsSB.value()
            startradius = self.startRadiusSB.value()
            endradius = self.endRadiusSB.value()
            delta = (endradius - startradius) / (steps - 1)
            radii = []
            for step in range(steps):
                radii.append(startradius + step * delta)
            #radii = [10,20,50]
            #self.showInfo(str(radii))
            prfeedback = QgsProcessingFeedback()

            selectedinputonly = self.selectedFeaturesCheckBox.isChecked()
            selectedrefonly = self.selectedRefFeaturesCheckBox.isChecked()
            plugincontext = dataobjects.createContext(prfeedback)
            self.showInfo('Plugin context: ' + str(plugincontext))
            #self.showInfo('GUI thread: ' + str(QThread.currentThread()) + ' ID: ' + str(QThread.currentThreadId()))
            ###### Testing QgsTask!!!
            context = QgsProcessingContext()
            # context = None ## (arguement 3 has unexpected type 'NoneType')
            self.showInfo('Normal context: ' + str(context))
            #context.setProject(QgsProject.instance())
            bufferalg=QgsApplication.processingRegistry().algorithmById('native:buffer')
            #bufferalg=QgsApplication.processingRegistry().algorithmById('qgis:buffer')
            unionalg=QgsApplication.processingRegistry().algorithmById('qgis:union')
            statalg=QgsApplication.processingRegistry().algorithmById('qgis:statisticsbycategories')

            #[p.name() for p in alg.parameterDefinitions()]
            for radius in radii:
                self.showInfo('Radius: ' + str(radius))
                params={
                  'INPUT': inputlayer,
                  'DISTANCE': radius,
                  'SEGMENTS': 10,
                  'DISSOLVE': True,
                  'END_CAP_STYLE': 0,
                  'JOIN_STYLE': 0,
                  'MITER_LIMIT': 10,
                  'OUTPUT':'/home/havatv/buffinp' + str(radius) + '.shp'
                  #'OUTPUT':'memory:'
                }
                buffinp = processing.run(bufferalg,params) #OK
                inpblayer = QgsProcessingUtils.mapLayerFromString(buffinp['OUTPUT'], plugincontext) #OK
                self.showInfo('Inp buffer #features: ' + str(inpblayer.featureCount()))
                provider = inpblayer.dataProvider() #OK
                #provider.addAttributes([QgsField('InputB', QVariant.Int)])
                provider.addAttributes([QgsField('InputB', QVariant.String, len=5)]) #OK, but data type?
                inpblayer.updateFields() #OK
                inpblayer.startEditing() #OK
                ##field_index = provider.fieldNameIndex('InputB')
                ##field_index = inpblayer.fields().lookupField('InputB')
                field_index = provider.fields().lookupField('InputB')
                #self.showInfo('inpb, field index: ' + str(field_index))
                ## Big problems! layer.getFeatures does not work, update of attributes does not work!???
                ##for f in provider.getFeatures():  # finner objekter
                for f in inpblayer.getFeatures():  # finner ingen!
                     self.showInfo('Feature (inpb): ' + str(f))
                     #attrs = { field_index : 'I' }
                     #provider.changeAttributeValues({ f.id() : attrs })
                     #inpblayer.changeAttributeValue(f.id(), field_index, 1)
                     inpblayer.changeAttributeValue(f.id(), field_index, 'I')
                     self.showInfo('Feature attr: ' + str(inpblayer.getFeature(f.id()).attributes()))
                inpblayer.commitChanges() #OK
                inpblayer.updateFields() #OK
                self.showInfo('Input buffer finished')
                self.showInfo('inpblayer: ' + str(inpblayer))

                params = {
                  'INPUT': reflayer,
                  'DISTANCE': radius,
                  'SEGMENTS': 10,
                  'DISSOLVE': True,
                  'END_CAP_STYLE': 0,
                  'JOIN_STYLE': 0,
                  'MITER_LIMIT': 10,
                  'OUTPUT':'/home/havatv/buffref' + str(radius) + '.shp'
                  #'OUTPUT':'memory:'
                }
                buffref = processing.run(bufferalg,params)
                refblayer=QgsProcessingUtils.mapLayerFromString(buffref['OUTPUT'],plugincontext)
                self.showInfo('Ref buffer #features: ' + str(refblayer.featureCount()))
                provider = refblayer.dataProvider()
                newfield = QgsField('RefB', QVariant.String, len=5)
                provider.addAttributes([newfield])
                refblayer.updateFields()
                refblayer.startEditing()
                #field_index = provider.fieldNameIndex('RefB')
                field_index = refblayer.fields().lookupField('RefB')
                self.showInfo('refb, field index: ' + str(field_index))

                for f in provider.getFeatures():
                    self.showInfo('Feature (refb): ' + str(f))
                    refblayer.changeAttributeValue(f.id(), field_index, 'R')
                refblayer.commitChanges()
                self.showInfo('Reference buffer finished')
                self.showInfo('refblayer: ' + str(refblayer))

                params={
                  'INPUT': inpblayer,
                  'OVERLAY': refblayer,
                  'OUTPUT':'/home/havatv/union' + str(radius) + '.shp'
                  #'OUTPUT':'memory:'
                }
                buffcomb = processing.run(unionalg,params)
                unionlayer = QgsProcessingUtils.mapLayerFromString(buffcomb['OUTPUT'],plugincontext)
                self.showInfo('Union buffer #features: ' + str(unionlayer.featureCount()))
                self.showInfo('Union finished')
                self.showInfo('buffcomb: ' + str(buffcomb['OUTPUT']))

                provider=unionlayer.dataProvider()
                provider.addAttributes([QgsField('Area', QVariant.Double)])
                provider.addAttributes([QgsField('Combined', QVariant.String, len=40)])
                unionlayer.updateFields()
                unionlayer.startEditing()
                #area_field_index = provider.fieldNameIndex('Area')
                area_field_index = unionlayer.fields().lookupField('Area') # OK
                self.showInfo('union, area field index: ' + str(area_field_index))
                #area_field_index = unionalllayer.fieldNameIndex('Area')
                #combined_field_index = provider.fields().lookupField('Combined')
                combined_field_index = unionlayer.fields().lookupField('Combined') # OK
                self.showInfo('union, combined field index: ' + str(combined_field_index))
                #combined_field_index = unionalllayer.fieldNameIndex('Combined')
                for f in provider.getFeatures():
                    self.showInfo('Feature: ' + str(f))
                    area = f.geometry().area()
                    unionlayer.changeAttributeValue(f.id(), area_field_index, area)
                    #iidx = provider.fieldNameIndex('InputB')
                    iidx = unionlayer.fields().lookupField('InputB')
                    #iidx = unionalllayer.fieldNameIndex('InputB')
                    #ridx = provider.fieldNameIndex('RefB')
                    ridx = unionlayer.fields().lookupField('RefB')
                    #ridx = unionalllayer.fieldNameIndex('RefB')
                #    cidx = provider.fieldNameIndex('CoverL')
                    i = f.attributes()[iidx]
                    r = f.attributes()[ridx]
                #    c = f.attributes()[cidx]
                    comb = ''
                    if i is not None:
                      if r is not None:
                        comb = str(i) + str(r)
                      else:
                        comb = str(i)
                    else:
                      if r is not None:
                        comb = str(r)
                      else:
                        comb = None
                    unionlayer.changeAttributeValue(f.id(), combined_field_index, comb)
                unionlayer.commitChanges()

                # Do the statistics
                params={
                  'INPUT': unionlayer,
                  'VALUES_FIELD_NAME': 'Area',
                  'CATEGORIES_FIELD_NAME': 'Combined',
                  'OUTPUT':'/home/havatv/stats.csv'
                  #'OUTPUT':'memory:'
                }

                #stats = processing.runalg('qgis:statisticsbycategories',
                #                          union['OUTPUT'], 'Area', 'Combined',
                #                          None, progress=None)
                stats = processing.run(statalg, params)
                #self.status.emit('Statistics done ' + str(radius) + ' ' + str(stats))
                ##self.status.emit('Statistics done ' + str(radius))
	        #continue
                
                currstats = {}
                with open(stats['OUTPUT'], 'r') as csvfile:
                  spamreader = csv.DictReader(csvfile)
                  for row in spamreader:
                    self.showInfo('Cat ' + row['Combined'] + ': ' +  str(row['sum']))
                    currstats[row['Combined']] = row['sum']
                

                statistics.append([radius, currstats])



                #algres = processing.runAlgorithm(alg,params, onFinish=None, feedback=None, context=None)['OUTPUT']

            # Denne funker, men kræsjer etter at den er ferdig:
            #task = QgsProcessingAlgRunnerTask(alg,params,plugincontext)
            # Denne funker, men kræsjer etter at den er ferdig:
            #task = QgsProcessingAlgRunnerTask(alg,params,context)
            #self.showInfo('Task: ' + str(task))
            #  connect()
            #task.begun.connect(self.task_begun)
            #task.taskCompleted.connect(self.task_completed)
            # Denne funker for mikrodatasett - ingen reaksjon for minidatasett:
            # kommer i tillegg til QGIS-progressbar på statuslinja
            #task.progressChanged.connect(self.task_progress)
            #task.taskTerminated.connect(self.task_stopped)
            #task.executed.connect(self.task_executed)


            #task.run()
            # Add the task to the task manager (is started ASAP)
            #QgsApplication.taskManager().addTask(task)  # Kræsjer qgis med trådproblemer
            # Kjører hele greia, men kræsjer ved avslutning.
            #self.showInfo('Buffer 1 startet')  # Denne funker


            self.showPlots(statistics)

            #self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            #self.button_box.button(QDialogButtonBox.Close).setEnabled(False)
            self.button_box.button(QDialogButtonBox.Cancel).setEnabled(True)
        except:
            import traceback
            self.showError(traceback.format_exc())
        else:
            pass
        # End of startworker


    # Very incomplete!
    def showPlots(self, stats):
      try:
        #BOSGraphicsView
        self.BOSscene.clear()
        viewprect = QRectF(self.BOSGraphicsView.viewport().rect())
        self.BOSGraphicsView.setSceneRect(viewprect)
        bottom = self.BOSGraphicsView.sceneRect().bottom()
        top = self.BOSGraphicsView.sceneRect().top()
        left = self.BOSGraphicsView.sceneRect().left()
        right = self.BOSGraphicsView.sceneRect().right()
        height = bottom - top
        width = right - left
        size = width
        self.showInfo("Top: " + str(top) + " Bottom: " + str(bottom) + " Left: " + str(left))
        if width > height:
            size = height
        padding = 3
        padleft = 23
        padright = 6
        padbottom = 10
        padtop = 6

        minx = padleft
        maxx = width - padright
        xsize = maxx - minx
        miny = padtop
        maxy = height - padbottom
        ysize = maxy - miny
        maxval = 0
        maxsize = 0
        sizes = []
        normoiirsizes = []
        normiiirsizes = []
        normiiorsizes = []
        sums = []
        for stat in stats:
            sizet, sizestats = stat
            size = float(sizet)
            sizes.append(size)
            #oiir, iiir, iior = sizestats
            oiir = float(sizestats['NULLR'])
            iiir = float(sizestats['IR'])
            iior = float(sizestats['INULL'])
            sum = oiir + iiir + iior
            normoiirsizes.append(oiir/sum)
            normiiirsizes.append(iiir/sum)
            normiiorsizes.append(iior/sum)
            #self.showInfo("OIIR: " + str(oiir) + " IIIR: " + str(iiir) + " IIOR: " + str(iior))
            if maxval < oiir:
                maxval = oiir
            if maxval < iiir:
                maxval = iiir
            if maxval < iior:
                maxval = iior
            if maxsize < size:
                maxsize = size
        self.showInfo("Maxval: " + str(maxval) + " Maxsize: " + str(maxsize) + " Steps: " + str(len(sizes)))
        # Prepare the graph
        boundingbox = QRect(padleft,padtop,xsize,ysize)
        #rectangle = QRectF(self.BOSGraphicsView.mapToScene(boundingbox))
        #rectangle = self.BOSGraphicsView.mapToScene(boundingbox)
        #self.BOSscene.addRect(rectangle)

        # Add vertical lines
        startx = padleft
        starty = padtop
        frompt = QPoint(startx, starty)
        start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
        endx = startx
        endy = padtop + ysize
        topt = QPoint(endx, endy)
        end = QPointF(self.BOSGraphicsView.mapToScene(topt))
        line = QGraphicsLineItem(QLineF(start, end))
        line.setPen(QPen(QColor(204, 204, 204)))
        self.BOSscene.addItem(line)
        for i in range(len(sizes)):
            size = sizes[i]
            startx = padleft + xsize * size / maxsize
            starty = padtop
            frompt = QPoint(startx, starty)
            start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
            endx = startx
            endy = padtop + ysize
            topt = QPoint(endx, endy)
            end = QPointF(self.BOSGraphicsView.mapToScene(topt))
            line = QGraphicsLineItem(QLineF(start, end))
            line.setPen(QPen(QColor(204, 204, 204)))
            self.BOSscene.addItem(line)
            labeltext = str(sizes[i])
            label = QGraphicsTextItem()
            font = QFont()
            font.setPointSize(6)
            label.setFont(font)
            label.setPos(startx-6,ysize+padtop-4)
            label.setPlainText(labeltext)
            self.BOSscene.addItem(label)

        # Add horizontal lines
        for i in range(11):
            startx = padleft
            starty = padtop + i * ysize/10.0
            frompt = QPoint(startx, starty)
            start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
            endx = padleft + xsize
            endy = starty
            topt = QPoint(endx, endy)
            end = QPointF(self.BOSGraphicsView.mapToScene(topt))
            line = QGraphicsLineItem(QLineF(start, end))
            line.setPen(QPen(QColor(204, 204, 204)))
            self.BOSscene.addItem(line)
            labeltext = str(i*10)+'%'
            label = QGraphicsTextItem()
            font = QFont()
            font.setPointSize(6)
            label.setFont(font)
            label.setPos(-2,ysize-starty+padtop-4)
            label.setPlainText(labeltext)
            self.BOSscene.addItem(label)
        # Plot Outside input, Inside reference
        first = True
        for i in range(len(sizes)):
            size = sizes[i]
            value = normoiirsizes[i]
            if first:
              first = False
            else:
              startx = padleft + xsize * prevx / maxsize
              starty = padtop + ysize * (1-prevy)
              frompt = QPoint(startx, starty)
              start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
              endx = padleft + xsize * size / maxsize
              endy = padtop + ysize * (1-value)
              topt = QPoint(endx, endy)
              end = QPointF(self.BOSGraphicsView.mapToScene(topt))
              line = QGraphicsLineItem(QLineF(start, end))
              line.setPen(QPen(self.ringcolour))
              self.BOSscene.addItem(line)
            prevx = size
            prevy = value
        # Plot Inside input, Inside reference
        first = True
        for i in range(len(sizes)):
            size = sizes[i]
            value = normiiirsizes[i]
            if first:
              first = False
            else:
              startx = padleft + xsize * prevx / maxsize
              starty = padtop + ysize * (1-prevy)
              frompt = QPoint(startx, starty)
              start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
              endx = padleft + xsize * size / maxsize
              endy = padtop + ysize * (1-value)
              topt = QPoint(endx, endy)
              end = QPointF(self.BOSGraphicsView.mapToScene(topt))
              line = QGraphicsLineItem(QLineF(start, end))
              self.BOSscene.addItem(line)
            prevx = size
            prevy = value
        # Plot Inside input, Outside reference
        first = True
        for i in range(len(sizes)):
            size = sizes[i]
            value = normiiorsizes[i]
            if first:
              first = False
            else: 
              startx = padleft + xsize * prevx / maxsize
              starty = padtop + ysize * (1-prevy)
              frompt = QPoint(startx, starty)
              start = QPointF(self.BOSGraphicsView.mapToScene(frompt))
              endx = padleft + xsize * size / maxsize
              endy = padtop + ysize * (1-value)
              topt = QPoint(endx, endy)
              end = QPointF(self.BOSGraphicsView.mapToScene(topt))
              line = QGraphicsLineItem(QLineF(start, end))
              self.BOSscene.addItem(line)
            prevx = size
            prevy = value
        # Do completeness
        #plotCompleteness()    

      except:
        import traceback
        #self.showInfo("Error plotting")
        self.showInfo(traceback.format_exc())





    # Handle the result of the processing
    def task_executed(self, ok, result):
        self.showInfo("Task executed: ")
        # + str(ok))
        # + " Res: " + str(result))

    def task_completed(self, ok, result):
        self.showInfo("Task completed")

    def task_begun(self):
        self.showInfo("Task begun.")

    def task_stopped(self):
        self.showInfo("Task stopped.")

    # Denne fungerer (blir kalt). Progressbar i statuslinja får samme data)
    def task_progress(self, prog):
        #self.showInfo("Task progress. " + str(prog))
        return

    def workerFinished(self, ok, ret):
        """Handles the output from the worker and cleans up after the
           worker has finished."""
        self.progressBar.setValue(0.0)
        self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
        self.button_box.button(QDialogButtonBox.Close).setEnabled(True)
        self.button_box.button(QDialogButtonBox.Cancel).setEnabled(False)
        # End of workerFinished

    def showError(self, text):
        """Show an error."""
        QgsMessageLog.logMessage('Error: ' + text, self.BOS,
                                 Qgis.Critical)

    def showInfo(self, text):
        """Show info."""
        QgsMessageLog.logMessage('Info: ' + text, self.BOS,
                                 Qgis.Info)

    # Implement the accept method to avoid exiting the dialog when
    # starting the work
    def accept(self):
        """Accept override."""
        pass

    # Implement the reject method to have the possibility to avoid
    # exiting the dialog when cancelling
    def reject(self):
        """Reject override."""
        # exit the dialog
        QDialog.reject(self)
