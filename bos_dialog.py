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
#from qgis.core import QgsProcessingAlgRunnerTask   # ok
from qgis.core import QgsApplication   # ok
from qgis.core import QgsProcessingContext  # thread manipulation?
from qgis.core import QgsProcessingFeedback

#from qgis.core import QgsTaskManager  # Added (http://www.opengis.ch/2018/06/22/threads-in-pyqgis3/)
 
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

        self.labelTextSize = 8
        self.titleTextSize = 10

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
        self.displacementButton.clicked.connect(self.showPlots)
        self.avgdispButton.clicked.connect(self.showAverageDisplacement)
        self.oscillationButton.clicked.connect(self.showOscillation)
        self.complmiscButton.clicked.connect(self.showComplenessMiscoding)
        self.saveSvgButton.clicked.connect(self.saveAsSVG)
        self.saveAsPdfButton.clicked.connect(self.saveAsPDF)
        # Global variable for the statistics
        self.statistics = []        




    def startWorker(self):
        """Initialises and starts."""
        try:
            # Initialise the statistics variable (to contain the results)
            self.statistics = []
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
            if reflayer is not None and reflayer.sourceCrs().isGeographic():
                self.showWarning('Geographic CRS used for the reference layer -'
                                 ' computations will be in decimal degrees!')
            # Algorithms
            bufferalg=QgsApplication.processingRegistry().algorithmById('native:buffer')
            #bufferalg=QgsApplication.processingRegistry().algorithmById('qgis:buffer')
            unionalg=QgsApplication.processingRegistry().algorithmById('qgis:union')
            intersectionalg=QgsApplication.processingRegistry().algorithmById('qgis:intersection')
            differencealg=QgsApplication.processingRegistry().algorithmById('qgis:difference')
            multitosinglealg=QgsApplication.processingRegistry().algorithmById('qgis:multiparttosingleparts')
            statalg=QgsApplication.processingRegistry().algorithmById('qgis:statisticsbycategories')
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
            #self.showInfo(str(radii))
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
            # context = None ## (arguement 3 has unexpected type 'NoneType')
            #self.showInfo('Normal context: ' + str(context))
            #context.setProject(QgsProject.instance())
            # I følge oppskrifta på opengis.ch:
            #alg=QgsApplication.processingRegistry().algorithmById('native:buffer')
            #alg=QgsApplication.processingRegistry().algorithmById('qgis:buffer')
            #[p.name() for p in alg.parameterDefinitions()]

            for radius in radii:
                # Buffer input
                params={
                  'INPUT': inputlayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT':'memory:Input buffer'
                }
                task = QgsProcessingAlgRunnerTask(bufferalg,params,context)
                task.executed.connect(partial(self.task_executed, context, radius, 'input'))
                QgsApplication.taskManager().addTask(task)
                self.showInfo('Input buffer: ' + str(radius))
                # Buffer reference
                params={
                  'INPUT': reflayer,
                  'DISTANCE': radius,
                  #'OUTPUT':'/home/havatv/test.shp'
                  'OUTPUT':'memory:Reference buffer'
                }
                task = QgsProcessingAlgRunnerTask(bufferalg,params,context)
                task.executed.connect(partial(self.task_executed, context, radius, 'reference'))
                QgsApplication.taskManager().addTask(task)
                self.showInfo('Ref buffer: ' + str(radius))


            #params={
            #  'INPUT': inputlayer,
            #  'DISTANCE': 100.0,
            #  #'OUTPUT':'/home/havatv/test.shp'
            #  'OUTPUT':'memory:Output buffer'
            #}

            ##  QgsProcessingAlgorithm, QVariantMap, QgsProcessingContext, QgsProcessingFeedback
            ## Denne funker, men kræsjer etter at den er ferdig:
            ##task = QgsProcessingAlgRunnerTask(alg,params,plugincontext)
            ## Denne funker, men kræsjer etter at den er ferdig:

            #task = QgsProcessingAlgRunnerTask(bufferalg,params,context) # kræsjer etter at algoritmen har kjørt ferdig

            ## I følge oppskrifta på opengis.ch:
            ##task = QgsProcessingAlgRunnerTask(alg,params,context,feedback)  # kræsjer ved oppstart
            ##self.showInfo('Task: ' + str(task))
            ##  connect()
            ##task.begun.connect(self.task_begun)
            ##task.taskCompleted.connect(self.task_completed)
            ## Denne funker for mikrodatasett - ingen reaksjon for minidatasett:
            ## kommer i tillegg til QGIS-progressbar på statuslinja
            ##task.progressChanged.connect(self.task_progress)
            ##task.taskTerminated.connect(self.task_stopped)
            ##task.executed.connect(self.task_executed) # Crash

            #iteration = 5   # Identifiserer hvilken iterasjon det er snakk om

            ## I følge oppskrifta på opengis.ch (partial legger inn context som første parameter?):

            #task.executed.connect(partial(self.task_executed, context, iteration))

            ##task.executed.connect(partial(self.task_executed, feedback))  # Funker ikke - må ha context?
            ## partial sets "context" as the first parameter - the first parameter of executed will then be given as the second parameter.

            ##task.run()
            ## Add the task to the task manager (is started ASAP)
            ## I følge oppskrifta på opengis.ch

            #QgsApplication.taskManager().addTask(task)  # Kræsjer qgis med trådproblemer

            ## Kjører hele greia, men kræsjer ved avslutning.
            #self.showInfo('Buffer 1 startet')  # Denne funker

            ##self.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
            ##self.button_box.button(QDialogButtonBox.Close).setEnabled(False)
            self.button_box.button(QDialogButtonBox.Cancel).setEnabled(True)
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
