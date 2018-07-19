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
from threading import Lock

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
        QgsApplication.taskManager().allTasksFinished.connect(self.all_tasks_completed)
        # Global variables with mutexes
        # Dictionary variable for input buffers
        self.inputbuffers = {}
        self.ibmutex = Lock()
        # Dictionary variable for reference buffers    
        self.referencebuffers = {}
        self.rbmutex = Lock()
        # Variables for statistics
        # Number of polygons:
        self.polycount = {};
        self.pcmutex = Lock()
        # Complenetess values:
        self.completeness = {};
        self.comutex = Lock()
        # Miscoding values:
        self.miscodings = {};
        self.mimutex = Lock()
        # Other statistics
        self.statistics = {}
        self.stmutex = Lock()


    def startWorker(self):
        """Initialises and starts."""
        try:
            layerindex = self.inputLayer.currentIndex()
            layerId = self.inputLayer.itemData(layerindex)
            self.inputlayer = QgsProject.instance().mapLayer(layerId)
            if self.inputlayer is None:
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
            self.statalg=QgsApplication.processingRegistry().algorithmById('qgis:statisticsbycategories')

            # Calculate the total length of lines in the layers
            self.inpgeomlength = 0
            for f in self.inputlayer.getFeatures():
                self.inpgeomlength = self.inpgeomlength + f.geometry().length()
            self.refgeomlength = 0
            for f in self.reflayer.getFeatures():
                self.refgeomlength = self.refgeomlength + f.geometry().length()


            # Number of steps and radii
            steps = self.stepsSB.value()
            startradius = self.startRadiusSB.value()
            endradius = self.endRadiusSB.value()
            delta = (endradius - startradius) / (steps - 1)
            self.radii = []
            for step in range(steps):
                self.radii.append(startradius + step * delta)
            #self.radii = [10,20,50]
            #self.showInfo(str(self.radii))
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
            for radius in self.radii:
                # Buffer input  # Works!
                params={
                  'INPUT': self.inputlayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT': 'memory:InputBuffer'
                }
                task = QgsProcessingAlgRunnerTask(self.bufferalg,params,context)
                # Add a few extra parameters (context, radius and "input") using "partial"
                task.executed.connect(partial(self.buffer_executed, context, radius, self.INPUT))
                QgsApplication.taskManager().addTask(task)
                #self.showInfo('Start Input buffer: ' + str(radius))
                # Buffer reference  # Works!
                params={
                  'INPUT': self.reflayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT': 'memory:ReferenceBuffer'
                }
                task = QgsProcessingAlgRunnerTask(self.bufferalg,params,context)
                # Add a few extra parameters (context, radius and "reference") using "partial"
                task.executed.connect(partial(self.buffer_executed, context, radius, self.REF))
                QgsApplication.taskManager().addTask(task)
                #self.showInfo('Start Ref buffer: ' + str(radius))


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

    ## Handle the result of the processing
    ## I følge oppskrifta på opengis.ch (funker med partial!)
    ##def task_executed(context, ok, result):
    #def task_executed(self, context, iteration, kind, ok, result): # funker også (med partial)
    ##def task_executed(self, ok, result):
    ##def task_executed(ok, result):
    #    self.showInfo("Task executed: ")
    #    self.showInfo("Iteration: " + str(iteration))
    #    self.showInfo("Kind: " + str(kind))
    #    self.showInfo("OK: " + str(ok))
    #    self.showInfo("Res: " + str(result))
    #    #self.showInfo("Context (encoding): " + str(context.defaultEncoding()))
    #    #self.showInfo("Context (thread): " + str(context.thread()))


    # Handle the result of a buffer operation
    # Starts intesection, difference and union algorithms
    # Global variables: self.inputbuffers (insert, access and remove),
    #   self.referencebuffers (insert, access and remove), self.reflayer
    #   (used as alg param), self.inputlayer (used as alg parameter).
    def buffer_executed(self, context, iteration, kind, ok, result):
        #self.showInfo("Buffer executed (" + str(kind) + '): ' +
        #              str(iteration) + ', OK: ' + str(ok) +
        #              ', Res: ' + str(result))
        if not ok:
            self.showInfo("Buffer failed - " + str(iteration) + ' ' + str(kind))
            return
        #blayer = result['OUTPUT'] ## blayer blir string!
        # Get the result (line) dataset from the buffer algorithm
        blayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        # Add attribute
        provider = blayer.dataProvider()
        newfield = QgsField('InputB', QVariant.String, len=5)
        if kind == self.REF:
            newfield = QgsField('RefB', QVariant.String, len=5)
        provider.addAttributes([newfield])
        blayer.updateFields()
        # Update the attribute
        blayer.startEditing()
        field_index = blayer.fields().lookupField('InputB')
        if kind == self.REF:
            field_index = blayer.fields().lookupField('RefB')
        #self.showInfo('refb, field index: ' + str(field_index))
        for f in provider.getFeatures():
            #self.showInfo('Feature (refb): ' + str(f))
            if kind == self.REF:
                # Set the attribute value to 'R'
                blayer.changeAttributeValue(f.id(), field_index, 'R')
            else:
                # Set the attribute value to 'I'
                blayer.changeAttributeValue(f.id(), field_index, 'I')
        blayer.commitChanges()

        if kind == self.INPUT:
            self.ibmutex.acquire()  # Important to acquire ibmutex first (deadlock)
            try:
                self.inputbuffers[iteration] = result['OUTPUT']
            finally:
                self.ibmutex.release()
        elif kind == self.REF:
            self.rbmutex.acquire()
            try:
                self.referencebuffers[iteration] = result['OUTPUT']
            finally:
                self.rbmutex.release()
        else:
            self.showInfo("Strange kind of buffer: " + str(kind))
        # Do line overlay:  # Works!
        if kind == self.INPUT:
            params={
              'INPUT': self.reflayer,
              #'OVERLAY': result['OUTPUT'],
              'OVERLAY': blayer,
              #'OVERLAY': QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context),
              'OUTPUT': 'memory:Intersection'
            }
            task = QgsProcessingAlgRunnerTask(self.intersectionalg, params, context)
            # Add a few extra parameters (context, radius) using "partial"
            task.executed.connect(partial(self.intersection_executed, context, iteration))
            QgsApplication.taskManager().addTask(task)
            #self.showInfo('Start Intersection: ' + str(iteration))
        elif kind == self.REF:
            # The reference buffer is used to remove parts of the input layer
            params={
              'INPUT': self.inputlayer,
              'OVERLAY': blayer,
              'OUTPUT': 'memory:Difference'
            }
            task = QgsProcessingAlgRunnerTask(self.differencealg,params,context)
            # Add a few extra parameters (context, radius) using "partial"
            task.executed.connect(partial(self.difference_executed, context, iteration))
            QgsApplication.taskManager().addTask(task)
            #self.showInfo('Start Difference: ' + str(iteration))

        todelete = []  # buffer sizes to remove (after handling)
        # Do union, if possible
        # Check if both buffers are available:
        self.ibmutex.acquire() # Important to acquire ibmutex first (deadlock)
        try:
            self.rbmutex.acquire()
            try:
                for key in self.inputbuffers:
                    if key in self.referencebuffers:
                        # Union input  # Does not work!
                        params={
                          #'INPUT': self.inputbuffers[key],
                          'INPUT': QgsProcessingUtils.mapLayerFromString(self.inputbuffers[key], context),
                          #'OVERLAY': self.referencebuffers[key],
                          'OVERLAY': QgsProcessingUtils.mapLayerFromString(self.referencebuffers[key], context),
                          'OUTPUT': 'memory:Union'
                        }
                        task = QgsProcessingAlgRunnerTask(self.unionalg,params,context)
                        # Add a few extra parameters (context, radius) using "partial"
                        task.executed.connect(partial(self.union_executed, context, iteration))
                        QgsApplication.taskManager().addTask(task)
                        #self.showInfo('Start Union: ' + str(iteration))
                        todelete.append(key)
                        #del self.inputbuffers[key]
                        #del self.referencebuffers[key]
                for key in todelete:
                    del self.inputbuffers[key]
                    del self.referencebuffers[key]
                    #self.showInfo('Removed key: ' + str(key))
            finally:
                self.rbmutex.release()
        finally:
            self.ibmutex.release()
    # end of buffer_executed


    # Handle the result of the intersection operation between the
    # reference (line) layer and the input buffer.
    # Only global accessed is self.completeness
    def intersection_executed(self, context, iteration, ok, result):
        #self.showInfo("Intersection executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        # Get the result (line) dataset from the intersection algorithm
        reflineinpbuflayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        #self.showInfo('Reference line Intersect input buffer #features: ' + str(reflineinpbuflayer.featureCount()))
        # Calculate the total length of lines
        reflinelength = 0
        for f in reflineinpbuflayer.getFeatures():
            reflinelength = reflinelength + f.geometry().length()
        #self.showInfo('Completeness: ' + str(reflinelength) + ' - ' + str(self.refgeomlength))
        if self.refgeomlength > 0:
           BOScompleteness = reflinelength / self.refgeomlength
        else:
           BOScompleteness = 0
           self.showInfo('refgeomlength = 0!')
        self.comutex.acquire()
        try: 
            self.completeness[iteration] = BOScompleteness
        finally:
            self.comutex.release()

        #if QgsApplication.taskManager().count() == 0:
        #    self.all_tasks_completed()
    # end of intersection_executed


    # Handle the result of the difference operation between the input
    # line layer and the refbuffer layer
    # Only global accessed is self.miscodings
    def difference_executed(self, context, iteration, ok, result):
        #self.showInfo("Difference executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        if not ok:
            self.showInfo("Difference failed - " + str(iteration))
            return
        # Get the result (line) dataset for the result
        inplinerefbuflayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        # Calculate the total length of lines
        inplinelength = 0
        for f in inplinerefbuflayer.getFeatures():
                    inplinelength = inplinelength + f.geometry().length()
        if self.inpgeomlength > 0:
            BOSmiscodings = inplinelength / self.inpgeomlength
        else:
            BOSmiscodings = 0
        #self.showInfo('Miscodings: ' + str(BOSmiscodings))
        # update the miscodings dictionary
        self.mimutex.acquire()
        try: 
            self.miscodings[iteration] = BOSmiscodings
        finally:
            self.mimutex.release()
        #if QgsApplication.taskManager().count() == 0:
        #    self.all_tasks_completed()
    # end of difference_executed


    # Handle the result of the union operation between the input
    # buffer and the reference buffer
    # Starts multiparttosinglepart algorithm
    # No global variables are accessed
    def union_executed(self, context, iteration, ok, result):
        #self.showInfo("Union executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        if not ok:
            self.showInfo("Union failed - " + str(iteration))
            return
        # Get the result (polygon) dataset from the union algorithm
        unionlayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        # Add attributes
        provider=unionlayer.dataProvider()
        provider.addAttributes([QgsField('Area', QVariant.Double)])
        provider.addAttributes([QgsField('Combined', QVariant.String, len=40)])
        unionlayer.updateFields()
        unionlayer.startEditing()
        area_field_index = unionlayer.fields().lookupField('Area') # OK
        #self.showInfo('union, area field index: ' + str(area_field_index))
        combined_field_index = unionlayer.fields().lookupField('Combined') # OK
        #self.showInfo('union, combined field index: ' + str(combined_field_index))
        # Update the attributes
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
        #self.showInfo('Start MultipartToSinglepart: ' + str(iteration))

        # Do the statistics
        params={
            'INPUT': unionlayer,
            'VALUES_FIELD_NAME': 'Area',
            'CATEGORIES_FIELD_NAME': 'Combined',
            #'OUTPUT':'/home/havatv/stats.csv'
            'OUTPUT': 'memory:Statistics'
        }
        task = QgsProcessingAlgRunnerTask(self.statalg,params,context)
        # Add extra parameters (context, iteration) using "partial"
        task.executed.connect(partial(self.stats_executed, context, iteration))
        QgsApplication.taskManager().addTask(task)
        #self.showInfo('Start MultipartToSinglepart: ' + str(iteration))
    # end of union_executed


    # Handle the result of the multiparttosinglepart operation (on the
    # union of the input and reference buffer dataset).
    # Global variable self.polycount updated
    def tosingle_executed(self, context, iteration, ok, result):
        #self.showInfo("To single executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        if not ok:
            self.showInfo("MultipartToSinglepart failed - " + str(iteration))
            return
        # Get the result (polygon) dataset from the multiparttosinglepart algorithm
        singlelayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        #self.showInfo('Polygon count finished')
        # Select the polygons that are outside input and inside reference
        xoqiquery = "\"Combined\"='R'"
        #xoqiquery = "\"Combined\"='NULLR'"
        singlelayer.selectByExpression (xoqiquery)
        polycountoi = singlelayer.selectedFeatureCount()
        self.pcmutex.acquire()
        try:
            self.polycount[iteration] = polycountoi
        finally:
            self.pcmutex.release()
        #if QgsApplication.taskManager().count() == 0:
        #    self.all_tasks_completed()
    # end of tosingle_executed


    # Handle the result of the statisticsbycategories operation (on
    # the union of the input and reference buffer).
    # Global variable self.statistics updated
    def stats_executed(self, context, iteration, ok, result):
        #self.showInfo("Stats executed: " + str(iteration) + ', OK: ' + str(ok) + ', Res: ' + str(result))
        if not ok:
            self.showInfo("Statistics failed - " + str(iteration))
            return
        # Get the result (polygon) dataset from the multiparttosinglepart algorithm
        statlayer = QgsProcessingUtils.mapLayerFromString(result['OUTPUT'], context)
        #self.showInfo("CSV file: " + str(result['OUTPUT']))
        #self.showInfo("Stat layer fields: " + statlayer.fields().names()[0])
        currstats = {}
        sumidx = statlayer.fields().lookupField('sum')
        self.showInfo("Sumindex: " + str(sumidx))
        for f in statlayer.getFeatures():
            sum = f.attributes()[sumidx]
            self.showInfo("Sum: " + str(sum))
            first = f.attributes()[0]
            self.showInfo("First: " + str(first))
            currstats[first] = sum
        self.stmutex.acquire()
        try:
            self.statistics[iteration] = currstats
        finally:
            self.stmutex.release()
        #if QgsApplication.taskManager().count() == 0:
        #    self.all_tasks_completed()
    # end of stats_executed


    # Wrap it up when all tasks have completed and all work is done!
    # Global variables accessed (read only): self.polycount,
    # self.completeness, self.miscodings, self.statistics
    def all_tasks_completed(self):
        # Must check that all the work has been done
        # Secure access to the global variables
        self.pcmutex.acquire()
        try:
            if len(self.polycount) < len(self.radii):
                return
        finally:
            self.pcmutex.release()
        self.comutex.acquire()
        try:
            if len(self.completeness) < len(self.radii):
                return
        finally:
            self.comutex.release()
        self.mimutex.acquire()
        try:
            if len(self.miscodings) < len(self.radii):
                return
        finally:
            self.mimutex.release()
        self.stmutex.acquire()
        try:
            if len(self.statistics) < len(self.radii):
                return
        finally:
            self.stmutex.release()
        self.showInfo("All tasks completed!")
        for radius in self.radii:
            self.showInfo("Radius: " + str(radius))
            self.showInfo("Polycount: " + str(self.polycount[radius]))
            self.showInfo("Completeness: " + str(self.completeness[radius]))
            self.showInfo("Miscodings: " + str(self.miscodings[radius]))
            self.showInfo("Stats - R: " + str(self.statistics[radius]['R']))
            self.showInfo("Stats - I: " + str(self.statistics[radius]['I']))
            self.showInfo("Stats - IR: " + str(self.statistics[radius]['IR']))
        # self.button_box.button(QDialogButtonBox.Ok).setEnabled(True)
        # self.button_box.button(QDialogButtonBox.Close).setEnabled(True)
        # self.button_box.button(QDialogButtonBox.Cancel).setEnabled(False)


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
