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
from functools import partial
from os.path import dirname
from os.path import join
#import os
import csv
import math

from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication, QObject, QThread
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
#from qgis.PyQt.QtWidgets import QPushButton, QProgressBar, QMessageBox
from qgis.PyQt.QtWidgets import QFileDialog
#from qgis.PyQt.QtWidgets import QGraphicsView, QGraphicsEllipseItem
from qgis.PyQt.QtWidgets import QGraphicsScene, QGraphicsLineItem, QGraphicsTextItem
from qgis.PyQt.QtGui import QFont
#from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtGui import QPen, QColor
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtPrintSupport import QPrinter
from qgis.PyQt.QtSvg import QSvgGenerator

from qgis.core import QgsField
from qgis.core import QgsProcessingAlgRunnerTask   # ok
from qgis.core import QgsApplication   # ok
from qgis.core import QgsProcessingContext  # thread manipulation?
from qgis.core import QgsProcessingFeedback
from qgis.core import QgsProcessingUtils

#from qgis.core import QgsTaskManager  # Added (http://www.opengis.ch/2018/06/22/threads-in-pyqgis3/)
 
from qgis.core import Qgis

from qgis.core import QgsMessageLog, QgsProject

#from sys.path import append
#append(dirname(__file__))
#from processing.core.Processing import processing
import processing
from processing.tools import dataobjects  # Not used


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

        self.labelTextSize = 8
        self.titleTextSize = 10

        self.INPUT = 'input'
        self.REF = 'reference'

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
        #self.displacementButton.clicked.connect(self.showPlots)
        #self.avgdispButton.clicked.connect(self.showAverageDisplacement)
        #self.oscillationButton.clicked.connect(self.showOscillation)
        #self.complmiscButton.clicked.connect(self.showComplenessMiscoding)
        #self.saveSvgButton.clicked.connect(self.saveAsSVG)
        #self.saveAsPdfButton.clicked.connect(self.saveAsPDF)
        # Global variable for the statistics
        self.statistics = []    

        # Global dictionary variable for input buffers
        self.inputbuffers = {}
        # Global dictionary variable for reference buffers    
        self.referencebuffers = {}

        # Global variables for statistics
        # Number of polygons:
        self.polycount = {};
        self.completeness = {};




    def startWorker(self):
        """Initialises and starts."""
        try:
            # Initialise the statistics variable (to contain the results)
            self.statistics = []
            layerindex = self.inputLayer.currentIndex()
            layerId = self.inputLayer.itemData(layerindex)
            inputlayer = QgsProject.instance().mapLayer(layerId)
            if inputlayer is None:
                self.showError(self.tr('No input layer defined'))
                return
            refindex = self.referenceLayer.currentIndex()
            reflayerId = self.referenceLayer.itemData(refindex)
            self.reflayer = QgsProject.instance().mapLayer(reflayerId)
            if layerId == reflayerId:
                self.showInfo('The reference layer must be different'
                              ' from the input layer!')
                return
            if self.reflayer is None:
                self.showError(self.tr('No reference layer defined'))
                return
            if self.reflayer is not None and self.reflayer.sourceCrs().isGeographic():
                self.showWarning('Geographic CRS used for the reference layer -'
                                 ' computations will be in decimal degrees!')
            # Algorithms
            self.bufferalg=QgsApplication.processingRegistry().algorithmById('native:buffer')
            #self.bufferalg=QgsApplication.processingRegistry().algorithmById('qgis:buffer')
            self.unionalg=QgsApplication.processingRegistry().algorithmById('qgis:union')
            self.intersectionalg=QgsApplication.processingRegistry().algorithmById('qgis:intersection')
            self.differencealg=QgsApplication.processingRegistry().algorithmById('qgis:difference')
            self.multitosinglealg=QgsApplication.processingRegistry().algorithmById('qgis:multiparttosingleparts')
            statalg=QgsApplication.processingRegistry().algorithmById('qgis:statisticsbycategories')

            # Calculate the total length of lines in the layers
            self.inpgeomlength = 0
            for f in inputlayer.getFeatures():
                self.inpgeomlength = self.inpgeomlength + f.geometry().length()
            self.refgeomlength = 0
            for f in self.reflayer.getFeatures():
                self.refgeomlength = self.refgeomlength + f.geometry().length()


            # Number of steps and radii
            steps = self.stepsSB.value()
            startradius = self.startRadiusSB.value()
            endradius = self.endRadiusSB.value()
            delta = (endradius - startradius) / (steps - 1)
            radii = []
            for step in range(steps):
                radii.append(startradius + step * delta)
            #radii = [10,20,50]
            #self.showInfo(str(radii))
            feedback = QgsProcessingFeedback()
            selectedinputonly = self.selectedFeaturesCheckBox.isChecked()
            selectedrefonly = self.selectedRefFeaturesCheckBox.isChecked()
            #plugincontext = dataobjects.createContext(feedback)
            #self.showInfo('Plugin context: ' + str(plugincontext))
            #self.showInfo('GUI thread: ' + str(QThread.currentThread()) + ' ID: ' + str(QThread.currentThreadId()))

            ###### Testing QgsTask!!!
            # I følge oppskrifta på opengis.ch
            context = QgsProcessingContext()
            #context = plugincontext
            #self.showInfo('Normal context: ' + str(context))
            #context.setProject(QgsProject.instance())
            for radius in radii:
                # Buffer input  # Works!
                params={
                  'INPUT': inputlayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT':'memory:Input buffer'
                }
                task = QgsProcessingAlgRunnerTask(self.bufferalg,params,context)
                # Add a few extra parameters (context, radius and "input") using "partial"
                task.executed.connect(partial(self.buffer_executed, context, radius, self.INPUT))
                QgsApplication.taskManager().addTask(task)
                self.showInfo('Start Input buffer: ' + str(radius))
                # Buffer reference  # Works!
                params={
                  'INPUT': self.reflayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT':'memory:Reference buffer'
                }
                task = QgsProcessingAlgRunnerTask(self.bufferalg,params,context)
                # Add a few extra parameters (context, radius and "reference") using "partial"
                task.executed.connect(partial(self.buffer_executed, context, radius, self.REF))
                QgsApplication.taskManager().addTask(task)
                self.showInfo('Start Ref buffer: ' + str(radius))


            ##task.begun.connect(self.task_begun)
            ##task.taskCompleted.connect(self.task_completed)
            ##task.progressChanged.connect(self.task_progress)
            ##task.taskTerminated.connect(self.task_stopped)

            #iteration = 5   # Identifiserer hvilken iterasjon det er snakk om

            ## I følge oppskrifta på opengis.ch (partial legger inn context som første parameter):
            ## context ser ut til å være helt nødvendig!
            #task.executed.connect(partial(self.task_executed, context, iteration))
            #self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            #self.button_box.button(QDialogButtonBox.Close).setEnabled(False)
            #self.button_box.button(QDialogButtonBox.Cancel).setEnabled(True)
        except:
            import traceback
            self.showError(traceback.format_exc())
        else:
            pass
        # End of startworker

    # Handle the result of the processing
    # I følge oppskrifta på opengis.ch (funker med partial!)
    #def task_executed(context, ok, result):
    def task_executed(self, context, iteration, kind, ok, result): # funker også (med partial)
    #def task_executed(self, ok, result):
    #def task_executed(ok, result):
        self.showInfo("Task executed: ")
        self.showInfo("Iteration: " + str(iteration))
        self.showInfo("Kind: " + str(kind))
        self.showInfo("OK: " + str(ok))
        self.showInfo("Res: " + str(result))
        #self.showInfo("Context (encoding): " + str(context.defaultEncoding()))
        #self.showInfo("Context (thread): " + str(context.thread()))

    # Handle the result of a buffer operation
    def buffer_executed(self, context, iteration, kind, ok, result):
        self.showInfo("Buffer executed (" + str(kind) + '): ' + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        #self.showInfo("Iteration: " + str(iteration))
        #self.showInfo("Kind: " + str(kind))
        #self.showInfo("OK: " + str(ok))
        #self.showInfo("Res: " + str(result))
        if not ok:
            self.showInfo("Buffer failed - " + str(iteration) + ' ' + str(kind))
            return

        # Testing...
        #blayer = result['OUTPUT'] ## blayer blir string!
        blayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        #fcnt = 0
        #for f in blayer.getFeatures():
        #    fcnt = fcnt + 1
        #self.showInfo("Feature count: " + str(fcnt))

        provider = blayer.dataProvider()
        newfield = QgsField('InputB', QVariant.String, len=5)
        if kind == self.REF:
            newfield = QgsField('RefB', QVariant.String, len=5)
        provider.addAttributes([newfield])
        blayer.updateFields()
        blayer.startEditing()
        field_index = blayer.fields().lookupField('InputB')
        if kind == self.REF:
            field_index = blayer.fields().lookupField('RefB')
        self.showInfo('refb, field index: ' + str(field_index))
        # Set the attribute value to 'R'
        for f in provider.getFeatures():
            #self.showInfo('Feature (refb): ' + str(f))
            if kind == self.REF:
                blayer.changeAttributeValue(f.id(), field_index, 'R')
            else:
                blayer.changeAttributeValue(f.id(), field_index, 'I')
        blayer.commitChanges()

        if kind == self.INPUT:
            self.inputbuffers[iteration] = result['OUTPUT']
        elif kind == self.REF:
            self.referencebuffers[iteration] = result['OUTPUT']
        else:
            self.showInfo("Strange kind of buffer: " + str(kind))
        # Do line overlay:  # Works!
        if kind == self.INPUT:
            params={
              'INPUT': self.reflayer,
              #'OVERLAY': result['OUTPUT'],
              'OVERLAY': blayer,
              #'OVERLAY': QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context),
              'OUTPUT':'memory:Intersection'
            }
            task = QgsProcessingAlgRunnerTask(self.intersectionalg,params,context)
            # Add a few extra parameters (context, radius) using "partial"
            task.executed.connect(partial(self.intersection_executed, context, iteration))
            QgsApplication.taskManager().addTask(task)
            self.showInfo('Start Intersection: ' + str(iteration))
        #elif kind == self.REF:

        todelete = []
        # Check if both buffers are available:
        for key in self.inputbuffers:
            if key in self.referencebuffers:
                # Union input  # Does not work!
                params={
                  #'INPUT': self.inputbuffers[key],
                  'INPUT': QgsProcessingUtils.mapLayerFromString(self.inputbuffers[key], context),
                  #'OVERLAY': self.referencebuffers[key],
                  #'OVERLAY': blayer,
                  'OVERLAY': QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context),
                  'OUTPUT':'memory:Union'
                }
                task = QgsProcessingAlgRunnerTask(self.unionalg,params,context)
                # Add a few extra parameters (context, radius) using "partial"
                task.executed.connect(partial(self.union_executed, context, iteration))
                QgsApplication.taskManager().addTask(task)
                self.showInfo('Start Union: ' + str(iteration))
                todelete.append(key)
                #del self.inputbuffers[key]
                #del self.referencebuffers[key]
        for key in todelete:
            del self.inputbuffers[key]
            del self.referencebuffers[key]
            self.showInfo('Removed key: ' + str(key))

    # end of buffer_executed


    def intersection_executed(self, context, iteration, ok, result):
        self.showInfo("Intersection executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        #self.showInfo("Intersection executed: ")
        #self.showInfo("Iteration: " + str(iteration))
        #self.showInfo("OK: " + str(ok))
        #self.showInfo("Res: " + str(result))



        # reference lines with input buffer (completeness)
        reflineinpbuflayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        #self.showInfo('Reference line Intersect input buffer #features: ' + str(reflineinpbuflayer.featureCount()))
        reflinelength = 0
        for f in reflineinpbuflayer.getFeatures():
            reflinelength = reflinelength + f.geometry().length()
        self.showInfo('Completeness: ' + str(reflinelength) + ' - ' + str(self.refgeomlength))
        if self.refgeomlength > 0:
           BOScompleteness = reflinelength / self.refgeomlength
        else:
           BOScompleteness = 0
           self.showInfo('refgeomlength = 0!')
        self.completeness[iteration] = BOScompleteness
    # end of intersection_executed

    def union_executed(self, context, iteration, ok, result):
        self.showInfo("Union executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        #self.showInfo("Union executed: ")
        #self.showInfo("Iteration: " + str(iteration))
        #self.showInfo("OK: " + str(ok))
        #self.showInfo("Res: " + str(result))
        if not ok:
            self.showInfo("Union failed - " + str(iteration))
            return
        unionlayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        provider=unionlayer.dataProvider()
        provider.addAttributes([QgsField('Area', QVariant.Double)])
        provider.addAttributes([QgsField('Combined', QVariant.String, len=40)])
        unionlayer.updateFields()
        unionlayer.startEditing()
        area_field_index = unionlayer.fields().lookupField('Area') # OK
        #self.showInfo('union, area field index: ' + str(area_field_index))
        combined_field_index = unionlayer.fields().lookupField('Combined') # OK
        #self.showInfo('union, combined field index: ' + str(combined_field_index))
        for f in provider.getFeatures():
            #self.showInfo('Feature: ' + str(f))
            area = f.geometry().area()
            unionlayer.changeAttributeValue(f.id(), area_field_index, area)
            iidx = unionlayer.fields().lookupField('InputB')
            ridx = unionlayer.fields().lookupField('RefB')
            i = f.attributes()[iidx]
            r = f.attributes()[ridx]
            # Set the 'Combined' attribute value to show the combination
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
            #self.showInfo('Combination: ' + str(comb))
            unionlayer.changeAttributeValue(f.id(), combined_field_index, comb)
        unionlayer.commitChanges()

        # Count polygons that are outside the input buffer and
        # inside the reference buffer.

        # Do multipart to singlepart: # OK
        params={
          #'INPUT': QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context),
          'INPUT': unionlayer,
          #'INPUT': result['OUTPUT'],
          'OUTPUT': 'memory:Singlepart'
        }
        task = QgsProcessingAlgRunnerTask(self.multitosinglealg,params,context)
        # Add extra parameters (context, iteration) using "partial"
        task.executed.connect(partial(self.tosingle_executed, context, iteration))
        QgsApplication.taskManager().addTask(task)
        self.showInfo('Start MultipartToSinglepart: ' + str(iteration))

    # end of union_executed


    def tosingle_executed(self, context, iteration, ok, result):
        self.showInfo("To single executed: ")
        self.showInfo("Iteration: " + str(iteration))
        self.showInfo("OK: " + str(ok))
        self.showInfo("Res: " + str(result))
        if not ok:
            self.showInfo("MultipartToSinglepart failed - " + str(iteration))
            return
        singlelayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        self.showInfo('Polygon count finished')
        xoqiquery = "\"Combined\"='R'"
        #xoqiquery = "\"Combined\"='NULLR'"
        singlelayer.selectByExpression (xoqiquery)
        polycountoi = singlelayer.selectedFeatureCount()
        self.polycount[iteration] = polycountoi
        self.showInfo('Polygon count finished')



    # end of tosingle_executed

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

    #def workerFinished(self, ok, ret):
    #    """Handles the output from the worker and cleans up after the
    #       worker has finished."""
    #    self.progressBar.setValue(0.0)
    #    self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
    #    self.button_box.button(QDialogButtonBox.Close).setEnabled(True)
    #    self.button_box.button(QDialogButtonBox.Cancel).setEnabled(False)
    #    # End of workerFinished

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
