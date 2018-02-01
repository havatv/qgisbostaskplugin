from time import sleep
from PyQt5.QtCore import QObject

###  Denne kjører fint fra Python-konsollet i QGIS med fila lagt inn
# i "Editor"

class TestTask( QgsTask ):

    def __init__(self, desc, time):
        QgsTask.__init__(self, desc)
        self.time = time

    def run(self):
        wait_time = self.time / 100.0
        for i in range(101):
            sleep(wait_time)
            self.setProgress(i)
            if self.isCancelled():
                self.stopped()
                return
        self.completed()

class MyPlugin( QObject ):

    def task_begun(self):
        print ("{} begun".format(self.sender().description()))
        #print ' begun'

    def task_completed(self):
        print ('*{}* complete'.format( self.sender().description() ))

    def task_stopped(self):
        print ('*{0:s}* cancelled!'.format( self.sender().description() ))

    def progress(self, val):
        #print val
        pass

    def newTask(self, task_name, length):
        task = TestTask(task_name, length)
        task.begun.connect(self.task_begun)
        task.taskCompleted.connect(self.task_completed)
        task.progressChanged.connect(self.progress)
        task.taskTerminated.connect(self.task_stopped)
        #QgsTaskManager.instance().addTask( task )
        QgsApplication.taskManager().addTask( task )
        return task

m = MyPlugin()
t1 = m.newTask("Task 1", 300)  # 3 sekunder
t2 = m.newTask("Task 2", 500)
t3 = m.newTask("Task 3", 1000)

