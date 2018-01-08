# -*- coding: utf-8 -*-
"""
/***************************************************************************
 BOS
                                 A QGIS plugin
 Implements the BOS method for assessing the accuracy of geographical line
 data sets
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
#2# from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication
#2# from PyQt4.QtGui import QAction, QIcon
#2# from PyQt4.QtGui import QMessageBox
from qgis.PyQt.QtCore import QSettings, QCoreApplication
#QFileInfo, 
from qgis.PyQt.QtCore import QTranslator, qVersion
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

#2# from qgis.core import QgsMapLayerRegistry, QgsMapLayer
#2# from qgis.core import QGis
from qgis.core import QgsProject, QgsMapLayer, QgsWkbTypes

# Plugin imports
import sys
import os.path
sys.path.append(os.path.dirname(__file__))
# Initialize Qt resources from file resources.py
import resources
# Import the code for the dialog
from .bos_dialog import BOSDialog


class BOS:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'BOS_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        # Declare instance attributes
        self.BOS = self.tr(u'BOS')
        self.BOSAMP = self.tr(u'&BOS')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(self.BOS)
        self.toolbar.setObjectName(self.BOS)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('BOS', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        # Create the dialog (after translation) and keep reference
        self.dlg = BOSDialog(self.iface)

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu and hasattr(self.iface, 'addPluginToVectorMenu'):
            self.iface.addPluginToVectorMenu(
                self.BOSAMP,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/BOS/bos.png'
        self.add_action(
            icon_path,
            text=self.tr(u'The BOS line accuracy assessment method'),
            callback=self.run,
            parent=self.iface.mainWindow())


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            if hasattr(self.iface, 'addPluginToVectorMenu'):
                self.iface.removePluginVectorMenu(
                    self.BOSAMP,
                    action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar


    def run(self):
        """Run method that performs all the real work"""

        # Populate the input and reference layer combo boxes
        #2# layers = QgsMapLayerRegistry.instance().mapLayers()  #2#
        layers = QgsProject.instance().mapLayers()
        layerslist = []
        for id in layers.keys():
            if layers[id].type() == QgsMapLayer.VectorLayer:
                if not layers[id].isValid():
                    QMessageBox.information(None,
                        self.tr('Information'),
                        'Layer ' + layers[id].name() + ' is not valid')
                if layers[id].geometryType() == QgsWkbTypes.LineGeometry:
                #if layers[id].wkbType() == QgsWkbTypes.LineGeometry:
                #if (layers[id].wkbType() == QGis.WKBLineString or
                #    layers[id].wkbType() == QGis.WKBLineString25D):   #2#
                    layerslist.append((layers[id].name(), id))
        if len(layerslist) == 0 or len(layers) == 0:
            QMessageBox.information(None,
               self.tr('Information'),
               self.tr('Line vector layers not found'))
            return
        # Add the layers to the layers combobox
        self.dlg.inputLayer.clear()
        for layerdescription in layerslist:
            self.dlg.inputLayer.addItem(layerdescription[0],
                                        layerdescription[1])
        self.dlg.referenceLayer.clear()
        # Add the layers to the layers combobox
        for layerdescription in layerslist:
            self.dlg.referenceLayer.addItem(layerdescription[0],
                                        layerdescription[1])

        # show the dialog
        self.dlg.show()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result:
            # Do something useful here - delete the line containing pass and
            # substitute with your code.
            pass
