from ilastik.workflow import Workflow

from lazyflow.graph import Graph

from ilastik.applets.dataSelection import DataSelectionApplet
from mriVolFilterApplet import MriVolFilterApplet
from mriVolReportApplet import MriVolReportApplet

from ilastik.applets.pixelClassification import PixelClassificationApplet
from ilastik.applets.featureSelection import FeatureSelectionApplet

import numpy as np
import vigra


class MriVolumetryWorkflowBase(Workflow):
    workflowName = "MRI Volumetry Base"

    def __init__(self, shell, headless, *args, **kwargs):

        # Create a graph to be shared by all operators
        graph = Graph()
        self._applets = []
        super(MriVolumetryWorkflowBase, self).__init__(shell, headless,
                                                       graph=graph, *args,
                                                       **kwargs)

        # Create applets
        self.mriVolFilterApplet = MriVolFilterApplet(self,
                                                     'Filter Predictions',
                                                     'PredictionFilter')

        self.mriVolReportApplet = MriVolReportApplet(self,
                                                     'Report', 'Report')

        self._applets.append(self.mriVolFilterApplet)
        self._applets.append(self.mriVolReportApplet)

    def connectLane(self, laneIndex, rawSlot, predSlot, labelNameSlot=None):
        opFilter = self.mriVolFilterApplet.topLevelOperator
        opMriVolFilter = opFilter.getLane(laneIndex)
        opReport = self.mriVolReportApplet.topLevelOperator
        opMriVolReport = opReport.getLane(laneIndex)

        # Connect top-level operators
        opMriVolFilter.RawInput.connect(rawSlot)
        opMriVolFilter.Input.connect(predSlot)
        if labelNameSlot is not None:
            opMriVolFilter.LabelNames.connect(labelNameSlot)

        opMriVolReport.RawInput.connect(rawSlot)
        opMriVolReport.Input.connect(opMriVolFilter.CachedOutput)
        opMriVolReport.LabelNames.connect(opMriVolFilter.LabelNames)
        opMriVolReport.ActiveChannels.connect(opMriVolFilter.ActiveChannels)

    @property
    def applets(self):
        return self._applets

    @property
    def imageNameListSlot(self):
        return self.dataSelectionApplet.topLevelOperator.ImageName

    def handleAppletStateUpdateRequested(self, child_ready=False):
        """
        Overridden from Workflow base class
        Called when an applet has fired the
        :py:attr:`Applet.appletStateUpdateRequested`

        This method will be called by the child classes with the result of
        their own applet readyness findings as keyword argument.
        """

        # if upstream is ready, we can enable the filter applet
        # (and vice-versa)
        self._shell.setAppletEnabled(self.mriVolFilterApplet,
                                     child_ready)

        # the filter operator is ready when the apply button has been
        # pressed at least once
        # FIXME why is CachedOutput ready even if ActiveChannels is not
        # set?
        op = self.mriVolFilterApplet.topLevelOperator
        filter_ready = child_ready
        for slot in (op.CachedOutput,):# op.ActiveChannels):
            filter_ready &= (len(slot) > 0 and
                             all(s.ready() for s in slot))

        self._shell.setAppletEnabled(self.mriVolReportApplet,
                                     filter_ready)


# standard workflow
class MriVolumetryWorkflowPrediction(MriVolumetryWorkflowBase):
    workflowName = "MRI Volumetry (from Prediction Maps)"
    workflowDisplayName = \
        "MRI Volumetry [Inputs: Raw Data, Pixel Prediction Map]"
    workflowDescription = "... TODO ..."

    def __init__(self, *args, **kwargs):
        super(self.__class__, self).__init__(*args, **kwargs)
        self.dataSelectionApplet = DataSelectionApplet(self,
                                                       "Input Data",
                                                       "Input Data", 
                                                supportIlastik05Import=False,
                                                       batchDataGui=False,
                                                       force5d=True)

        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue(['Raw Data',
                                               'Prediction Maps'])

        self._applets.insert(0, self.dataSelectionApplet)

    def connectLane(self, laneIndex):
        opData = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)
        super(self.__class__, self).connectLane(laneIndex,
                                                opData.ImageGroup[0],
                                                opData.ImageGroup[1])

    def handleAppletStateUpdateRequested(self):
        nRoles = 2  # both, raw and prediction have to be provided
        slot = self.dataSelectionApplet.topLevelOperator.ImageGroup
        if len(slot) > 0:
            ready = True
            for sub in slot:
                ready = ready and \
                    all([sub[i].ready() for i in range(nRoles)])
        else:
            ready = False

        super(self.__class__, self).handleAppletStateUpdateRequested(ready)


# add pixel classification to the standard workflow
class MriVolumetryWorkflowPixel(MriVolumetryWorkflowBase):
    workflowName = "MRI Volumetry (from Pixel Classification)"
    workflowDisplayName = "Pixel Classification + MRI Volumetry"

    def __init__(self, *args, **kwargs):
        super(self.__class__, self).__init__(*args, **kwargs)

        self.dataSelectionApplet = DataSelectionApplet(
            self, "Input Data", "Input Data", supportIlastik05Import=False,
            batchDataGui=False, force5d=True)

        opDataSelection = self.dataSelectionApplet.topLevelOperator
        opDataSelection.DatasetRoles.setValue(['Raw Data',])

        self.featureSelectionApplet = FeatureSelectionApplet(
            self, "Feature Selection", "FeatureSelections", "Original")

        self.pcApplet = PixelClassificationApplet(self, "PixelClassification")
        opClassify = self.pcApplet.topLevelOperator

        self._applets.insert(0, self.dataSelectionApplet)
        self._applets.insert(1, self.featureSelectionApplet)
        self._applets.insert(2, self.pcApplet)

    def connectLane(self, laneIndex):
        # Get a handle to each operator
        opData = self.dataSelectionApplet.topLevelOperator.getLane(laneIndex)
        opTrainingFeatures = \
            self.featureSelectionApplet.topLevelOperator.getLane(laneIndex)
        opClassify = self.pcApplet.topLevelOperator.getLane(laneIndex)

        # Input Image -> Feature Op
        #         and -> Classification Op (for display)
        opTrainingFeatures.InputImage.connect(opData.Image)
        opClassify.InputImages.connect(opData.Image)

        # Feature Images -> Classification Op (for training, prediction)
        opClassify.FeatureImages.connect(opTrainingFeatures.OutputImage)
        opClassify.CachedFeatureImages.connect(opTrainingFeatures.CachedOutputImage)

        # Training flags -> Classification Op (for GUI restrictions)
        opClassify.LabelsAllowedFlags.connect(opData.AllowLabels)

        super(self.__class__, self).connectLane(
            laneIndex, opData.ImageGroup[0],
            opClassify.CachedPredictionProbabilities,
            opClassify.LabelNames)

    def handleAppletStateUpdateRequested(self):
        nRoles = 1  # we need only raw images
        slot = self.dataSelectionApplet.topLevelOperator.ImageGroup
        if len(slot) > 0:
            ready = True
            for sub in slot:
                ready = ready and \
                    all([sub[i].ready() for i in range(nRoles)])
        else:
            ready = False

        input_ready = ready
        cumulated_readiness = ready
        self._shell.setAppletEnabled(self.featureSelectionApplet,
                                     cumulated_readiness)

        def reallyReady(s):
            r = (len(s) > 0
                 and s[0].ready()
                 and np.prod(s[0].meta.shape) > 0)
            return r

        opFeatureSelection = self.featureSelectionApplet.topLevelOperator
        features_ready = reallyReady(opFeatureSelection.OutputImage)
        cumulated_readiness &= features_ready
        self._shell.setAppletEnabled(self.pcApplet, cumulated_readiness)

        slot = self.pcApplet.topLevelOperator.PredictionProbabilities
        predictions_ready = reallyReady(slot)

        cumulated_readiness &= predictions_ready

        # Problems can occur if the features or input data are changed
        # during live update mode.
        # Don't let the user do that.
        opPixelClassification = self.pcApplet.topLevelOperator
        live_update_active = not opPixelClassification.FreezePredictions.value

        self._shell.setAppletEnabled(self.dataSelectionApplet,
                                     not live_update_active)
        self._shell.setAppletEnabled(self.featureSelectionApplet,
                                     input_ready and not live_update_active)

        # also problematic: if live update is not active, downstream
        # can't access the predictions, or gets invalid predictions
        cumulated_readiness &=live_update_active

        super(self.__class__, self).handleAppletStateUpdateRequested(
            cumulated_readiness)

