#!/usr/bin/env python

#  This file is part of XOPTFOIL-JX.

#  XOPTFOIL-JX is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

#  XOPTFOIL-JX is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

#  You should have received a copy of the GNU General Public License
#  along with XOPTFOIL-JX.  If not, see <http://www.gnu.org/licenses/>.

#  Copyright (C) 2020 Matthias Boese

# imports
import xml.etree.ElementTree as ET
import argparse
import json
import sys, os
from matplotlib import pyplot as plt
import matplotlib.image as mpimg
import numpy as np
import pip
import f90nml
from copy import deepcopy
from scipy.signal import savgol_filter

# paths and separators
bs = "\\"
presetsPath = 'ressources' + bs + 'presets'
imagesPath = 'ressources' + bs + 'images'
logoName = 'strakmachine.png'

# fixed filenames
T1_polarInputFile = 'iPolars_T1.txt'
T2_polarInputFile = 'iPolars_T2.txt'

# fonts
csfont = {'fontname':'Segoe Print'}

# number of decimals in the generated input-files
Cl_decimals = 4 # lift
Cd_decimals = 6 # drag
Al_decimals = 4 # alpha

# fontsizes
fs_infotext = 10

# colours
cl_infotext = 'aqua'
cl_polar_change = 'orange'
cl_T1_polar = 'g'
cl_T2_polar = 'b'


################################################################################
#
# install missing packages
#
################################################################################
def install_and_import(package):
    import importlib
    try:
        importlib.import_module(package)
    except ImportError:
        import pip
        pip.main(['install', package])
    finally:
        globals()[package] = importlib.import_module(package)

#TODO improve !! e.g. use linear interpolation etc.
################################################################################
#
# helper function that finds a peak
#
################################################################################
def findPeak(list, height):
        # init peak-searcher
        peak_max = 0.0
        peak_max_idx = 0
        peak_left_idx = 0
        peak_right_idx = 0
        searchLeftBorder = True
        searchRightBorder = False

        #first: find absolute maximum
        idx = 0
        for value in list:
            if value > peak_max:
                peak_max = value
                peak_max_idx = idx
            idx = idx+1

        peak_limit = peak_max - height

        # second: find left and right border
        idx = 0

        # walk through the list
        for value in list:
            if (searchLeftBorder == True):
                #searching for peak_left_idx
                if value >= peak_limit:
                    peak_left_idx = idx
                    peak_right_idx = idx
                    searchLeftBorder = False
                    searchRightBorder = True
            if (searchRightBorder == True):
                #searching for peak_right_idx
                if value <= peak_limit:
                    peak_right_idx = idx
                    searchRightBorder = False
            idx = idx + 1

         # calculate new maximum idx as the idx in the middle between the borders
        #print (peak_max_idx) #Debug
        #peak_max_idx = (peak_right_idx + peak_left_idx)/2 Debug
        #print (peak_max_idx, peak_left_idx, peak_right_idx) #Debug

        return peak_max_idx



################################################################################
#
# example-dictionary for creating .json-file
#
################################################################################
strakdata = {
            # folder containing the inputs-files
            "inputFolder": 'ressources',
            # folder containing the output / result-files
            "outputFolder": 'build',
            # name of XFLR5-xml-file
            "XMLfileName": 'wing.xml',
            # ReSqrt(Cl)-numbers of the strak
            "ReNumbers": [220000, 190000, 160000, 130000, 100000, 70500],
            # determines max Re-number to use for Type2 polar. Will switch to
            # Type1-polar at maxReFactor * ReNumber[i]
            "maxReFactor": 2.5,
            # list of chord-lenghts
            "chordlengths": [],
            # ReSqrt(Cl) of root airfoil if using chord-lenghts instead of Re-numbers
            "ReSqrtCl": '150000',
            # root airfoil name
            "seedFoilName": 'rg15.dat',
            # type of the strak that shall be developed
            "strakType":  'Generic',
             # name of the xoptfoil-inputfile for strak-airfoil(s)
            "strakInputFileName": 'istrak.txt',
            # generate batchfile for running Xoptfoil
            "generateBatchfile" : 'true',
            # name of the batchfile
            "batchfileName" : 'make_strak.bat',
            # operating-mode for strakmachine
            "operatingMode" : 'default',
            # use always root-airfoil or use predecessing airfoil
            "useAlwaysRootfoil" : 'false',
            # skip the generation of polars (to save time if already done before)
            "skipPolarGeneration": 'false',
            # adapt initial_perturb in input file according to differenc in Re-numbers
            "adaptInitialPerturb": 'true',
            # projected maxGlide loss (percent), absolte value
            "maxGlideLoss": 0.008,
            # projected maxSpeed gain between root and strak-airfoil (percent)
            "maxSpeedGain": 0.5,
            # projected maxLift gain between root and strak-airfoil (percent)
            "maxLiftGain": 0.3
            }


def getPresetInputFileName(strakType):
    # get real path of the script
    pathname = os.path.dirname(sys.argv[0])
    scriptPath = os.path.abspath(pathname)

    # get list of all existing files
    fileList = getListOfFiles(scriptPath + bs + presetsPath)

    # search the whole list of files for the desired strak-type
    for name in fileList:
        if name.find(strakType) >= 0:
            return name

################################################################################
#
# inputfile class
#
################################################################################
class inputFile:
    def __init__(self, strakType):
        self.values = {}
        self.presetInputFileName = ""
        self.idx_maxSpeed = 0
        self.idx_maxGlide = 0
        self.idx_preClmax = 0
        self.idx_Clmax = 0

        # get real path of the script
        pathname = os.path.dirname(sys.argv[0])
        scriptPath = os.path.abspath(pathname)
        presetInputFiles = getListOfFiles(scriptPath + bs + presetsPath)
        self.getInputFileName(presetInputFiles, strakType)

        # read input-file as a Fortan namelist
        self.values = f90nml.read(self.presetInputFileName)
        #operatingConditions = self.values["operating_conditions"]#Debug
        #print (operatingConditions)#Debug

        # clean-up file
        self.removeDeactivatedOpPoints() #TODO remove

    # removes an op-Point if weighting is beyond a certain limit
    def removeDeactivatedOpPoints(self):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]

        # make a copy
        newOperatingConditions = operatingConditions.copy()

        # clear all opPoints of the copy
        self.deleteAllOpPoints(newOperatingConditions)

       # walk through the opPoints
        for idx in range(len(operatingConditions["weighting"])):
            # get OpPoint-weight

            if (operatingConditions["weighting"][idx] >= 0.001):
                # copy this opPoint to the new operating-conditions
                newOperatingConditions["name"].append(operatingConditions["name"][idx])
                newOperatingConditions["op_mode"].append(operatingConditions["op_mode"][idx])
                newOperatingConditions["op_point"].append(operatingConditions["op_point"][idx])
                newOperatingConditions["optimization_type"].append(operatingConditions["optimization_type"][idx])
                newOperatingConditions["target_value"].append(operatingConditions["target_value"][idx])
                newOperatingConditions["weighting"].append(operatingConditions["weighting"][idx])
                newOperatingConditions['noppoint'] = newOperatingConditions['noppoint'] + 1

        # write-back operatingConditions
        self.values["operating_conditions"] = newOperatingConditions


    def getInputFileName(self, fileList, strakType):
        # search the whole list of files for the desired strak-type
        for name in fileList:
            if name.find(strakType) >= 0:
                self.presetInputFileName = name
                return

##    def getPresetInputFileName(self):
##        return self.presetInputFileName


    def changeTargetValue(self, keyName, targetValue):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]
        # get OpPoint-names
        opPointNames = operatingConditions["name"]
        idx = 0
        for key in opPointNames:
            if key == keyName:
                # get type of op-point
                opPointType = operatingConditions['op_mode'][idx]

                # limit the number of decimals
                if (opPointType == 'spec-cl'):
                    # target-value is drag-value
                    targetValue = round(targetValue, Cd_decimals)
                elif (opPointType == 'spec-al'):
                    # target-value is lift-value
                    targetValue = round(targetValue, Cl_decimals)

                # change target value
                operatingConditions['target_value'][idx] = targetValue

                # write-back operatingConditions
                self.values["operating_conditions"] = operatingConditions
                return
            idx = idx + 1


    def changeOpPoint(self, keyName, op_point):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]
        # get OpPoint-names
        opPointNames = operatingConditions["name"]
        idx = 0
        for key in opPointNames:
            if key == keyName:
                # get type of op-point
                opPointType = operatingConditions['op_mode'][idx]

                # limit the number of decimals
                if (opPointType == 'spec-cl'):
                    # opPoint-value is lift-value
                    op_point = round(op_point, Cl_decimals)
                elif (opPointType == 'spec-al'):
                    # opPoint-value is alpha-value
                    op_point = round(op_point, Al_decimals)

                # change op_point
                operatingConditions['op_point'][idx] = op_point
                # write-back operatingConditions
                self.values["operating_conditions"] = operatingConditions
                return
            idx = idx + 1


    def changeWeighting(self, idx, new_weighting):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]

         # set new weighting
        operatingConditions['weighting'][idx] = new_weighting



    def getOpPoint(self, keyName):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]
        # get OpPoint-names
        opPointNames = operatingConditions["name"]
        idx = 0
        for key in opPointNames:
            if key == keyName:
                # return op_point
                return operatingConditions['op_point'][idx]
            idx = idx + 1

    def getTargetValue(self, keyName):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]
        # get OpPoint-names
        opPointNames = operatingConditions["name"]
        idx = 0
        for key in opPointNames:
            if key == keyName:
                # return op_point
                return operatingConditions['target_value'][idx]
            idx = idx + 1


    # gets the type of an opPoint ('spec-cl' or 'spec-al')
    def getOpPointType(self, keyName):
        # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]
        # get OpPoint-names
        opPointNames = operatingConditions["name"]
        idx = 0
        for key in opPointNames:
            if key == keyName:
                # return op_point-type (="op-mode")
                return operatingConditions['op_mode'][idx]
            idx = idx + 1

    def setInitialPerturb(self, ReDiff):
        ReDiffList =  [(150000/5), 150000]
        perturbList = [(0.01/5), 0.01]
        pso_tolList = [(0.0015/5), 0.0015]

        # calculate corresponding perturb
        perturb = np.interp(ReDiff, ReDiffList, perturbList)
        optimization_options = self.values["optimization_options"]
        optimization_options['initial_perturb'] = perturb

        # also adapt pso_tol!!!
        pso_tol = round(np.interp(ReDiff, ReDiffList, pso_tolList),6)
        particle_swarm_options = self.values["particle_swarm_options"]
        particle_swarm_options['pso_tol'] = pso_tol
        print("Re-Diff is %d, setting initial_perturb to %.4f and pso_tol to %.5f" %\
         (ReDiff, perturb, pso_tol))


    def adaptMaxLift(self, polarData):
        # get new values from polar
        alphaMaxLift = polarData.alpha_maxLift
        pre_alphaMaxLift = polarData.alpha_maxLift
        CL_MaxLift = polarData.CL_maxLift
        pre_CL_MaxLift = polarData.pre_CL_maxLift

        # determine type of op-point
        op_type = self.getOpPointType('alphaClmax')

        # set new oppoint-value
        if (op_type == 'spec-al'):
            self.changeOpPoint("alphaClmax", alphaMaxLift)
        else:
            self.changeOpPoint("alphaClmax", CL_MaxLift)

        # adapt target-value to polar
        self.adaptTargetValueToPolar("alphaClmax", polarData)

        # determine type of op-point
        op_type = self.getOpPointType('preClmax')

        # set new oppoint-value
        if (op_type == 'spec-al'):
            self.changeOpPoint("preClmax", pre_alphaMaxLift)
        else:
            self.changeOpPoint("preClmax", pre_CL_MaxLift)

        # adapt target-value to polar
        self.adaptTargetValueToPolar("preClmax", polarData)


    def adaptMaxSpeed(self, polarData):
        # get new values from polar
        CL_maxSpeed = polarData.CL_maxSpeed

        self.changeOpPoint('maxSpeed', CL_maxSpeed)
        self.adaptTargetValueToPolar("maxSpeed", polarData)


    # adapts Max-Glide and dependend values to given polar
    def adaptMaxGlide(self, polarData):
        # get polar values, Cl MaxGlide, alpha Max-Glide
        AlphaMaxGlide = polarData.alpha_maxGlide
        CL_maxGlide = polarData.CL_maxGlide

        # set new op-Points and target-values
        self.changeOpPoint('maxGlide', CL_maxGlide)
        self.adaptTargetValueToPolar("maxGlide", polarData)

        try:
            self.changeOpPoint('alphaMaxGlide', AlphaMaxGlide)
            self.adaptTargetValueToPolar("alphaMaxGlide", polarData)
        except:
            pass

        try:
            self.changeOpPoint('slopeMaxGlide',CL_maxGlide)
        except:
            pass

    def generateOpPoints(self, numOpPoints, Cl_min, Cl_max, alpha_Cl_max):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]

        # clear operating conditions
        self.deleteAllOpPoints(operatingConditions)

        # calculate the intervall
        diff = (Cl_max - Cl_min) / (numOpPoints-1)

        # always start at Cl_min for first opPoint
        op_point = Cl_min
        op_mode = 'spec-cl'
        optimization_type = 'target-drag'
        target_value = 0.0
        weighting = 1.0
        reynolds = None

        # now build up new opPoints
        for i in range(numOpPoints):
            # set generic op-point-name
            name = "op_%s" % i

            # last opPoint has always lift-target
            if (i == (numOpPoints-1)):
                op_point_value = round(alpha_Cl_max, Al_decimals)
                op_mode = 'spec-al'
                optimization_type = 'target-lift'
                target_value = Cl_max
            else:
                # round opPoint
                op_point_value = round(op_point, Cl_decimals)

            # add new opPoint to dictionary
            self.addOppoint(name, op_mode, op_point_value, optimization_type,
                                            target_value, weighting, reynolds)
            # increment op-point
            op_point = op_point + diff

        # set new number of opPoints
        operatingConditions['noppoint'] = numOpPoints
#        print(self.values["operating_conditions"])#Debug
#        print("Done.")#Debug


    def findClosestClOpPoint(self, Cl):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]
        numOpPoints = len(operatingConditions["op_point"])
        name = None
        idx = -1

        for i in range(1, numOpPoints):
            value_left = operatingConditions["op_point"][i-1]
            value_right = operatingConditions["op_point"][i]
            name_left = operatingConditions["name"][i-1]
            name_right = operatingConditions["name"][i]

            if (Cl >= value_left) & (Cl <= value_right):
                # we found the correct interval. Which one is closer ?
                diff_To_left = Cl - value_left
                diff_To_right = value_right - Cl

                if (diff_To_left < diff_To_right):
                    return (name_left, i-1)
                else:
                    return (name_right, i)

        return (name, idx)


    def getLastOpPoint(self):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]
        numOpPoints = len(operatingConditions["op_point"])

        # return last opPoint
        name = operatingConditions["name"][numOpPoints-1]
        idx = numOpPoints-1
        return (name, idx)

    def printOpPoints(self):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]
        opPointNames = operatingConditions["name"]
        opPoints = operatingConditions["op_point"]
        targetValues = operatingConditions["target_value"]

        print(opPointNames)
        print(opPoints)
        print(targetValues)
        print("Done.")


    # distributes main-oppoints
    def distributeMainOpPoints(self, CL_maxSpeed, CL_maxGlide, pre_CL_maxLift,
                               pre_alpha_maxLift, CL_maxLift, alpha_maxLift):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]
        opPointNames = operatingConditions["name"]
        opPoints = operatingConditions["op_point"]

        # get opPoint
        (opPoint_maxLift, self.idx_Clmax) = self.getLastOpPoint()

        # change value
        self.changeOpPoint(opPoint_maxLift, pre_alpha_maxLift)
        self.changeTargetValue(opPoint_maxLift, pre_CL_maxLift)

        self.idx_preClmax = self.idx_Clmax-1
        opPoint_preClmax = opPointNames[self.idx_preClmax]

        # get opPoint
        (opPoint_maxGlide, self.idx_maxGlide) =\
                            self.findClosestClOpPoint(CL_maxGlide)

        # correct oppoint, if necessary
        if (self.idx_maxGlide >= self.idx_preClmax):
            self.idx_maxGlide = self.idx_preClmax -1
            opPoint_maxGlide = opPointNames[self.idx_maxGlide]

        # get opPoint
        (opPoint_maxSpeed, self.idx_maxSpeed) =\
                                 self.findClosestClOpPoint(CL_maxSpeed)

        # correct oppoint, if necessary
        if (self.idx_maxSpeed >= self.idx_maxGlide):
            self.idx_maxSpeed = self.idx_maxGlide -1
            opPoint_maxSpeed = opPointNames[self.idx_maxSpeed]

        # change values
        self.changeOpPoint(opPoint_preClmax, (pre_CL_maxLift*0.980))
        self.changeOpPoint(opPoint_maxGlide, CL_maxGlide)
        self.changeOpPoint(opPoint_maxSpeed, CL_maxSpeed)

        # change names
        opPointNames[self.idx_Clmax] = 'alphaClmax'
        opPointNames[self.idx_preClmax] = 'preClmax'
        opPointNames[self.idx_maxGlide] = 'maxGlide'
        opPointNames[self.idx_maxSpeed] = 'maxSpeed'


    def distributeEqually(self, start, end):
         # get operating-conditions
        operatingConditions = self.values["operating_conditions"]

        # get operating-modes
        op_mode_start = operatingConditions["op_mode"][start]
        op_mode_end = operatingConditions["op_mode"][end]

        # get Cl-values
        if (op_mode_start == 'spec-cl'):
            Cl_start = operatingConditions["op_point"][start]
        else:
            Cl_start = operatingConditions["target_value"][start]

        if (op_mode_end == 'spec-cl'):
            Cl_end = operatingConditions["op_point"][end]
        else:
            Cl_end = operatingConditions["target_value"][end]

        # calculate the interval
        num_intervals = end - start
        Cl_interval = (Cl_end - Cl_start) / num_intervals

        print(Cl_start, Cl_end, Cl_interval, num_intervals)

        num = 1
        for idx in range(start+1, end):
            op_mode = operatingConditions["op_mode"][idx]
            op_type = operatingConditions["optimization_type"][idx]

            # only "spec-cl" op-points shalle be affected
            if (op_mode == 'spec-cl') and (op_type != 'min-glide-slope'):
                newValue = round(Cl_start + (num*Cl_interval), Cl_decimals)
                operatingConditions["op_point"][idx] = newValue
                num = num + 1


    # distribute all intermediate-oppoints
    def distributeIntermediateOpPoints(self, polarData):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]

        # distribute the opPoints between the main opPoints equally
        self.distributeEqually(0, self.idx_maxSpeed)
        self.distributeEqually(self.idx_maxSpeed, self.idx_maxGlide)
        self.distributeEqually(self.idx_maxGlide, self.idx_preClmax)

        #print(self.values["operating_conditions"])#Debug
        #print("Done.")#Debug


    def SetWeightings(self, params):
        if (params.weighting_mode == 'linear_progression'):
            operatingConditions = self.values["operating_conditions"]#Debug
            max_weigth = 3.0
            min_weight = 0.7

            num_intervals = self.idx_Clmax
            diff = (max_weigth - min_weight) / num_intervals

            for idx in range(num_intervals+1):
                weight = round(min_weight + (idx*diff), 2)
                self.changeWeighting(idx, weight)

        print(operatingConditions["weighting"])#Debug
        print("Done.")


    def adaptReNumbers(self, polarData):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]

       # walk through the opPoints
        for idx in range(len(operatingConditions["weighting"])):#TODO use other key
            if(operatingConditions["op_mode"][idx] == 'spec-cl'):
                # check the op-point-value
                Cl = operatingConditions["op_point"][idx]
                if (Cl <= polarData.Cl_switchpoint_Type2_Type1_polar):
                    # adapt maxRe --> Type 1 oppoint
                    operatingConditions["reynolds"][idx] = int(polarData.maxRe)
                    print("adapted oppoint @ Cl = %0.3f, Type 1, Re = %d\n" % \
                          (Cl, int(polarData.maxRe)))

    # shifts a list of oppoints by a certain difference. Does not change the
    # target-values
    def shiftOpPoints(self, diff, opPointList):
         # shift all oppoints in list
        for opPointName in opPointList:
            try:
                opPointValue = self.getOpPoint(opPointName)
                opPointValue = opPointValue + diff
                self.changeOpPoint(opPointName, opPointValue)
            except:
                print("opPoint %s was skipped" % opPointName)


    # scales the target-values of a list of oppoints by a certain factor.
    def scaleTargetValues(self, factor, opPointList):
         # scale all target-values in list
        for opPointName in opPointList:
            try:
                value = self.getTargetValue(opPointName)
                value = value * factor
                self.changeTargetValue(opPointName, value)
            except:
                print("opPoint %s was skipped" % opPointName)


    # shifts the target-values of a list of oppoints by a certain difference.
    def shiftTargetValues(self, diff, opPointList):
         # scale all target-values in list
        for opPointName in opPointList:
            try:
                value = self.getTargetValue(opPointName)
                self.changeTargetValue(opPointName, value)
            except:
                print("opPoint %s was skipped" % opPointName)


    # the target-value of the given oppoint will be set according to the
    # value that is found in the polar
    def adaptTargetValueToPolar(self, opPointName, polar):
        # get value of opPoint
        opPointValue = self.getOpPoint(opPointName)
        print(polar.polarName)#debug

        # what kind of value is it?
        opPointType = self.getOpPointType(opPointName)

        if (opPointType == 'spec-al'):
            # oppoint is alpha-value, get target-value from polar
            targetValue = polar.find_CL(opPointValue)
        else:
            # oppoint is Cl-value, get target-value from polar
            targetValue = polar.find_CD(opPointValue)

        # set new target-value of oppoint
        self.changeTargetValue(opPointName, targetValue)

    # All "maxlift"-dependend opPoints in the inputfile will be "transferred"
    # according to the polar of the strak-airfoil in polardata. The oppoints in
    # the inputfile exactly match the polar of the root-airfoil. For physical
    # reasons (lower Re-number) it is not possible to completely restore the
    # polar of the root-airfoil at the Re-number of the strak-airfoil. But the
    # polar should come as close as possible to the polar of the root-airfoil in
    # some specified points. So the target opPoints for the strak-airfoil, that
    # will be calculated here, are a mixture between the polar of the root-
    # airfoil and the polar of the not optimized strak-airfoil.
    def transferMaxLift(self, params, polarData):
        # assign the polars to local variables
        root_polar = params.merged_polars[0]
        strak_polar = polarData

        # is this the polar of the root-airfoil ?
        if (root_polar == strak_polar):
            # do nothing
            return

        # 'preClmax'
        try:
            # get type of op-point
            op_type = self.getOpPointType('preClmax')

            # get some polar values
            alpha_root = root_polar.pre_alpha_maxLift
            alpha_strak = strak_polar.pre_alpha_maxLift
            CL_root = root_polar.pre_CL_maxLift
            CD_root = root_polar.pre_CD_maxLift

            if (op_type == 'spec-al'):
                # calculate new value
                target_alpha = ((alpha_root * params.maxLiftGain) +
                                 (alpha_strak * (1.0 - params.maxLiftGain)))

                # get according Cl from root-polar
                target_CL = root_polar.find_CL(target_alpha)

                # set new values
                self.changeOpPoint("preClmax", target_alpha)
                self.changeTargetValue("preClmax", target_CL)
            #else:
                # not implementeed yet
##                # calculate new value
##                target_alpha = ((alpha_root * params.maxLiftGain) +
##                                 (alpha_strak * (1.0 - params.maxLiftGain)))
##
##                # get according Cl from root-polar
##                target_CL = root_polar.find_CL(target_alpha)
##
##                # set new values
##                self.changeOpPoint("preClmax", target_alpha)
##                self.changeTargetValue("preClmax", target_CL)

        except:
            print("opPoint \'preClmax\' was skipped")

        # 'alphaClmax'
        try:
            # get root-polar-values
            alpha_root = root_polar.alpha_maxLift
            CL_root = root_polar.CL_maxLift
            CD_root = root_polar.CD_maxLift

            # get strak-polar-values
            alpha_strak = strak_polar.alpha_maxLift
            CL_strak = strak_polar.CL_maxLift
            CD_strak = strak_polar.CD_maxLift

            # new value is value between root-polar and strak polar
            target_CL = ((CL_root * params.maxLiftGain) +
                                (CL_strak * (1.0 - params.maxLiftGain)))

            target_alpha = ((alpha_root * params.maxLiftGain) +
                             (alpha_strak * (1.0 - params.maxLiftGain)))

            # set new values
            self.changeOpPoint("alphaClmax", target_alpha)
            self.changeTargetValue("alphaClmax", target_CL)

        except:
            print("opPoint \'alphaClmax\' was skipped")


    # all target-values will be scaled "downward" according
    # to the factor in CL_CD_MaxGlide between root-polar and strak-polar
    def transferMaxGlide(self, params, polarData):
        # assign the polars to local variables
        root_polar = params.merged_polars[0]
        strak_polar = polarData

        # is this the polar of the root-airfoil ?
        if (root_polar == strak_polar):
            # do nothing
            return

        # calculate factor between root-polar maxGlide and strak-polar maxGlide,
        # include an additional "loss" in max-glide that is a parameter
        factor = (root_polar.CL_CD_max) / (strak_polar.CL_CD_max * (1.00 - params.maxGlideLoss))

        # create List of opPoints to be affected. The target-values of these
        # oppoints will be "shifted", according to the calculated difference
        opPointList = ['preGlide','helperPreGlide', 'maxGlide','helperKeepGlide',
                       'keepGlide', 'helperPreClmax', 'preClmax']

        self.scaleTargetValues(factor, opPointList)


    def transferMaxSpeed(self, params, polarData):
        # assign the polars to local variables
        root_polar = params.merged_polars[0]
        strak_polar = polarData

        # is this the polar of the root-airfoil ?
        if (root_polar == strak_polar):
            # do nothing
            return

        # op-point 'keepSpeed', if existing in input-file
        try:
            # get CL-value / op-Point
            CL_keepSpeed = self.getOpPoint("keepSpeed")

            # get polar-values (root and strak-polar)
            CD_keepSpeed_root = root_polar.find_CD(CL_keepSpeed)
            CD_keepSpeed_strak = strak_polar.find_CD(CL_keepSpeed)

            # new target-value is value between root-polar and strak-polar
            CD_keepSpeed_target = ((CD_keepSpeed_root * params.maxSpeedGain) + # part coming from root-airfoil
                            (CD_keepSpeed_strak * (1.0 - params.maxSpeedGain)))# part coming from not optimized strak-airfoil

            # set new target-value
            self.changeTargetValue("keepSpeed", CD_keepSpeed_target)
        except:
            print("opPoint keepSpeed was skipped")

        # op-point 'maxSpeed', if existing in input-file
        try:
            # get CL-value / op-Point
            CL_maxSpeed = self.getOpPoint("maxSpeed")

            # get polar-values (root and strak-polar)
            CD_maxSpeed_root = root_polar.find_CD(CL_maxSpeed)
            CD_maxSpeed_strak = strak_polar.find_CD(CL_maxSpeed)

            # new target-value is value between root-polar and strak polar
            CD_maxSpeed_target = ((CD_maxSpeed_root * params.maxSpeedGain) +
                           (CD_maxSpeed_strak * (1.0 - params.maxSpeedGain)))

            self.changeTargetValue("maxSpeed", CD_maxSpeed_target)
        except:
            print("opPoint maxSpeed was skipped")

       # op-point 'preSpeed', if existing in input-file
        try:
            # get CL-value / op-Point
            CL_preSpeed = self.getOpPoint("preSpeed")

            # get polar-values (root and strak-polar)
            CD_preSpeed_root = root_polar.find_CD(CL_preSpeed)
            CD_preSpeed_strak = strak_polar.find_CD(CL_preSpeed)

            # new target-value is value between root-polar and strak polar
            CD_preSpeed_target = ((CD_preSpeed_root * params.maxSpeedGain) +
                           (CD_preSpeed_strak * (1.0 - params.maxSpeedGain)))

            self.changeTargetValue("preSpeed", CD_preSpeed_target)
        except:
            print("opPoint preSpeed was skipped")


    # adapt all target-values to the given polar-data
    def adaptAllOppointsToPolar(self, polarData):
        # get operating-conditions
        operatingConditions = self.values["operating_conditions"]
        num_points = operatingConditions['noppoint']

        # all target-values will be set to the corresponding polar-value
        for i in range(num_points):
            name = operatingConditions["name"][i]
            self.adaptTargetValueToPolar(name, polarData)

        # adapt Re-numbers for Type2 / Type1 oppoints
        self.adaptReNumbers(polarData)


    # transfer oppoints to a new polar, keeping the shape of the original polar/
    # oppoints
    def transferOppointsKeepShape(self, params, polarData):
        # transfer maxLift-values
        self.transferMaxLift(params, polarData)

        # transfer maxGlide-values
        self.transferMaxGlide(params, polarData)

        # transfer maxSpeed-values
        self.transferMaxSpeed(params, polarData)


    def deleteAllOpPoints(self, operatingConditions):
        # clear operating conditions
        operatingConditions["name"] = []
        operatingConditions["op_mode"] = []
        operatingConditions["op_point"] = []
        operatingConditions["optimization_type"] = []
        operatingConditions["target_value"] = []
        operatingConditions["weighting"] = []
        operatingConditions["reynolds"] = []
        operatingConditions['noppoint'] = 0


    def clearGeoTargets(self):
        if 'geometry_targets' in self.values:
            del self.values['geometry_targets']



    def addOppoint(self, name, op_mode, op_point, optimization_type,
                                            target_value, weighting, reynolds):
         # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]

        # append new oppoint
        operatingConditions["name"].append(name)
        operatingConditions["op_mode"].append(op_mode)
        operatingConditions["op_point"].append(op_point)
        operatingConditions["optimization_type"].append(optimization_type)
        operatingConditions["target_value"].append(target_value)
        operatingConditions["weighting"].append(weighting)
        operatingConditions["reynolds"].append(reynolds)
        operatingConditions['noppoint'] = operatingConditions['noppoint'] + 1


    # add a "target-drag" oppoint to operating-conditions
    def addTargetPolarOppoint(self, Cl, Cd):
        self.addOppoint('target_polar', 'spec-cl', Cl, 'target-drag', Cd, 1.0)


    # delete all existing oppoints and set new ones from polar-data
    def SetOppointsFromPolar(self, polarData, numOppoints):
        Cl_min = polarData.CL[0]
        Cl_max = polarData.CL_maxLift
        Cl_increment = (Cl_max - Cl_min) / numOppoints

        # clear operating conditions
        self.deleteAllOpPoints(self.values["operating_conditions"])

        # clear any existing geo-targets
        self.clearGeoTargets()

        # add new oppoints
        for i in range (numOppoints):
            Cl = round(Cl_min + (i * Cl_increment), Cl_decimals)
            Cd = round(polarData.find_CD(Cl), Cd_decimals)
            #print "Cl:%f, Cd:%f" % (Cl, Cd) #Debug
            self.addTargetPolarOppoint(Cl, Cd)


    def getOperatingConditions(self):
         # get operating-conditions from dictionary
        operatingConditions = self.values["operating_conditions"]

        return operatingConditions

    def writeToFile(self, fileName):
        # delete 'name'
        operatingConditions = self.values["operating_conditions"]
        operatingConditionsBackup = operatingConditions.copy()
        del(operatingConditions['name'])
        self.values["operating_conditions"] = operatingConditions

        # write to file
        print("writing input-file %s..." % fileName)
        f90nml.write(self.values, fileName, True)

        # restore 'name'
        self.values["operating_conditions"] = operatingConditionsBackup.copy()
        print("Done.")


################################################################################
#
# strakData class
#
################################################################################
class strakData:
    def __init__(self):
        self.inputFolder = ''
        self.outputFolder = ''
        self.airfoilFolder = ''
        self.xmlFileName = None
        self.strakInputFileName = 'i-strak.txt'
        self.ReSqrtCl = 150000
        self.numOpPoints = 16
        self.weighting_mode = 'constant'
        self.useWingPlanform = True
        self.generateBatch = True
        self.batchfileName = 'make_strak.bat'
        self.wingData = None
        self.strakType = "F3F"
        self.operatingMode = 'default'
        self.useAlwaysRootfoil = False
        self.adaptInitialPerturb = True
        self.skipPolarGeneration = False
        self.seedFoilName = ""
        self.matchPolarFoilName = ""
        self.smoothSeedfoil = True
        self.smoothMatchPolarFoil = True
        self.ReNumbers = []
        self.CL_min = -0.1
        self.chordLengths = []
        self.maxReFactor = 3.0
        self.maxReNumbers = []
        self.Cl_switchpoint_Type2_Type1_polar = 0.05
        self.polarFileNames = []
        self.polarFileNames_T1 = []
        self.polarFileNames_T2 = []
        self.inputFileNames = []
        self.T1_polars = []
        self.T2_polars = []
        self.merged_polars = []
        #self.targetPolars = []
        self.maxGlideLoss = 0.008
        self.maxSpeedGain = 0.5
        self.maxLiftGain = 0.3


    ############################################################################
    # function that returns a list of Re-numbers
    def get_ReList(params):
        return params.ReNumbers


    ############################################################################
    # function that calculates dependend values
    def calculateDependendValues(self):

        # calculate List of Re-numers, if wingdata available
        if (self.wingData != None):
            # clear the list of chord-lenghts
            self.chordLengths = []

            # get list of all chord-lengths of the wing
            chordLengths = params.wingData.get('chordLengths')

            # copy the list
            self.chordLengths = chordLengths

        # is there a list of chord-lengths available ?
        if (self.chordLengths != []):
            # clear the list of Re-numbers
            self.ReNumbers = []

            # get Re-number of root-airfoil
            rootRe = params.ReSqrtCl

            # get chord-length of root-airfoil
            rootChord = self.chordLengths[0]

            # calculate list of Re-numbers
            for chord in chordLengths:
                Re = (rootRe * chord) / rootChord
                self.ReNumbers.append(Re)

        # calculate list of max Re-numbers
        for Re in self.ReNumbers:
            ReMax = Re * self.maxReFactor
            self.maxReNumbers.append(ReMax)

        # calculate Cl where polar-generation is going to switch from
        # type2- to type1-polar
        self.Cl_switchpoint_Type2_Type1_polar =\
                   ((self.ReNumbers[0] * self.ReNumbers[0]))/\
                   ((self.maxReNumbers[0])*(self.maxReNumbers[0]))

        print("polar-generation will switch vom type2 to type1 at Cl = %.3f\n"\
         % self.Cl_switchpoint_Type2_Type1_polar)


################################################################################
#
# polarGraph class
#
################################################################################
class polarGraph:
    def __init__(self):
        return

    def plotLogo(self, ax, scriptDir):
        image = mpimg.imread(scriptDir + bs + imagesPath + bs + logoName)
        ax.imshow(image)
        ax.set_axis_off()

    def plotLiftDragOptimizationPoints(self, ax, polar):
        print("plotting CL over CD target-op-points for Re = %.0f...\n"\
              % (polar.Re))

        # check if there are operationg-conditions available
        if (polar.operatingConditions == None):
            return
        else:
            operatingConditions = polar.operatingConditions
            numOpPoints = len(operatingConditions["op_point"])

        for idx in range(numOpPoints):
            # get op-mode and type
            op_mode = operatingConditions["op_mode"][idx]
            op_type = operatingConditions["optimization_type"][idx]
            op_name = operatingConditions["name"][idx]

            if (op_mode == 'spec-cl') and (op_type != 'min-glide-slope'):

                # get CD from target-value
                x = operatingConditions["target_value"][idx]

                # get CL
                y = operatingConditions["op_point"][idx]

                print("target-op-point[%d] \'%s\', CL: %f, CD:%f" % (idx, op_name, x, y))

                # plot
                ax.plot(x, y, 'y.')

        print("Done.\n\n")


    def plotPolarChange(self, ax, rootPolar):
        if (rootPolar.Cl_switchpoint_Type2_Type1_polar != 999999):
            xlimits = ax.get_xlim()

            ax.axhline(y=rootPolar.Cl_switchpoint_Type2_Type1_polar,
                              xmin = xlimits[0], xmax = xlimits[1],
                              color = cl_polar_change)

            ax.text(xlimits[1], 0.3, 'Type 2',
                    transform = ax.transAxes,
                    horizontalalignment = 'right',
                    verticalalignment = 'bottom',
                    color = cl_polar_change)

            ax.text(xlimits[1], 0.1, 'Type 1',
                    transform = ax.transAxes,
                    horizontalalignment = 'right',
                    verticalalignment = 'bottom',
                    color = cl_polar_change)


    def plotLiftDragPolar(self, ax, polars):
        # set axes and labels
        self.setAxesAndLabels(ax, 'Cl, Cd', 'Cd', 'Cl')

        # get polar of root-airfoil
        rootPolar = polars[0]

        # set y-axis manually
        ax.set_ylim(min(rootPolar.CL) - 0.2, max(rootPolar.CL) + 0.2)

        # plot horizontal line where polar changes from T1 to T2
        #self.plotPolarChange(ax, rootPolar)

        # all polars
        for polar in polars:
            # determine idx for changing colors
            switchIdx = polar.T2_T1_switchIdx

            if (polar == rootPolar):
                T1_label = 'T1-polar'
                T2_label = 'T2-polar'
            else:
                T1_label = None
                T2_label = None

            # plot lower (T1)-part of polar
            x = polar.CD[0:switchIdx+1]
            y = polar.CL[0:switchIdx+1]
            # plot CL, CD
            ax.plot(x, y, (cl_T1_polar+'-'), label=T1_label)

            # plot upper (T2)-part of polar
            x = polar.CD[switchIdx:len(polar.CD)]
            y = polar.CL[switchIdx:len(polar.CL)]
            # plot CL, CD
            ax.plot(x, y, (cl_T2_polar+'-'), label=T2_label)

            # plot optimization points
            self.plotLiftDragOptimizationPoints(ax, polar)

            # plot max_speed
            x = polar.CD[polar.maxSpeed_idx]
            y = polar.CL[polar.maxSpeed_idx]

            # additonal text for root polar only
            if (polar == rootPolar):
                ax.plot(x, y, marker='o',color=cl_infotext)
                ax.annotate('maxSpeed (root) @ Cl = %.2f, Cd = %.4f' % (y, x),
                 xy=(x,y), xytext=(20,10), textcoords='offset points',
                      fontsize = fs_infotext, color=cl_infotext)
            else:
                ax.plot(x, y, 'o', color=cl_infotext)


            # plot max_glide
            x = polar.CD[polar.maxGlide_idx]
            y = polar.CL[polar.maxGlide_idx]

            # additonal text for root polar only
            if (polar == rootPolar):
                ax.plot(x, y, marker='o', color=cl_infotext)
                ax.annotate('maxGlide (root) @ Cl = %.2f, Cd = %.4f' % (y, x),
                 xy=(x,y), xytext=(20,0), textcoords='offset points',
                      fontsize = fs_infotext, color=cl_infotext)
            else:
                ax.plot(x, y, 'o', color=cl_infotext)

            # plot max lift
            x = polar.CD[polar.maxLift_idx]
            y = polar.CL[polar.maxLift_idx]

            # additonal text for root polar only
            if (polar == rootPolar):
                ax.plot(x, y, marker='o', color=cl_infotext)
                ax.annotate('maxLift (root) @ Cl = %.2f, Cd = %.4f' %(y,x),
                  xy=(x,y), xytext=(10,10), textcoords='offset points',
                    fontsize = fs_infotext, color=cl_infotext)
            else:
                ax.plot(x, y, 'o', color=cl_infotext)

            ax.legend(loc='upper left')

    def plotLiftOverAlphaOptimizationPoints(self, ax, polar):
        print("plotting CL over alpha target-op-points for Re = %.0f...\n"\
              % (polar.Re))

        # check if there are operationg-conditions available
        if (polar.operatingConditions == None):
            return
        else:
            operatingConditions = polar.operatingConditions
            numOpPoints = len(operatingConditions["op_point"])

        for idx in range(numOpPoints):
            # get op-mode
            op_mode = operatingConditions["op_mode"][idx]
            op_name = operatingConditions["name"][idx]

            if (op_mode == 'spec-al'):
                # get CL
                x = operatingConditions["op_point"][idx]

                # get alpha from target-value
                y = operatingConditions["target_value"][idx]

                print("target-op-point[%d] \'%s\', alpha:%f, CL: %f,"\
                 % (idx, op_name, x, y))
                # plot
                ax.plot(x, y, 'y.')

        print("Done.\n\n")

    def plotLiftOverAlphaPolar(self, ax, polars):
        # set axes and labels
        self.setAxesAndLabels(ax, 'Cl, alpha', 'alpha', 'Cl')

        # get polar of root-airfoil
        rootPolar = polars[0]

        # set y-axis manually
        ax.set_ylim(min(rootPolar.CL) - 0.1, max(rootPolar.CL) + 0.2)

        # plot horizontal line where polar changes from T1 to T2
        #self.plotPolarChange(ax, rootPolar)

        # all polars
        for polar in polars:

            if (polar == rootPolar):
                T1_label = 'T1-polar'
                T2_label = 'T2-polar'
            else:
                T1_label = None
                T2_label = None

            # determine idx for changing colors
            switchIdx = polar.T2_T1_switchIdx

            # plot lower (T1)-part of polar
            x = polar.alpha[0:switchIdx+1]
            y = polar.CL[0:switchIdx+1]
            # plot CL, CD
            ax.plot(x, y, (cl_T1_polar+'-'), label=T1_label)

            # plot upper (T2)-part of polar
            x = polar.alpha[switchIdx:len(polar.CD)]
            y = polar.CL[switchIdx:len(polar.CL)]
            # plot CL, CD
            ax.plot(x, y, (cl_T2_polar+'-'), label=T2_label)
            ax.legend(loc='upper left')

            # plot max Speed
            x = polar.alpha[polar.maxSpeed_idx]
            y = polar.CL[polar.maxSpeed_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # additonal text for root polar only
            if (polar == rootPolar):
                ax.annotate('maxSpeed (root) @ alpha = %.2f, Cl = %.2f' %\
                  (x, y), xy=(x,y),
                  xytext=(40,10), textcoords='offset points',
                  fontsize = fs_infotext, color=cl_infotext)

            # plot max Glide
            x = polar.alpha[polar.maxGlide_idx]
            y = polar.CL[polar.maxGlide_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # additonal text for root polar only
            if (polar == rootPolar):
                ax.annotate('maxGlide (root) @ alpha = %.2f, Cl = %.2f' %\
                  (x, y), xy=(x,y),
                  xytext=(40,0), textcoords='offset points',
                  fontsize = fs_infotext, color=cl_infotext)

            # plot max lift
            x = polar.alpha[polar.maxLift_idx]
            y = polar.CL[polar.maxLift_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # additonal text for root polar only
            if (polar == rootPolar):
                ax.annotate('maxLift (root) @ alpha = %.2f, Cl = %.2f' %\
                  (x, y), xy=(x,y),
                  xytext=(-80,15), textcoords='offset points',
                  fontsize = fs_infotext, color=cl_infotext)

        # plot optimization-points
        self.plotLiftOverAlphaOptimizationPoints(ax, polar)


    def setAxesAndLabels(self, ax, title, xlabel, ylabel):

        # set title of the plot
        text = (title)
        #ax.set_title(text, fontsize = 30, color="darkgrey")

        # set axis-labels
        ax.set_xlabel(xlabel, fontsize = 20, color="darkgrey")
        ax.set_ylabel(ylabel, fontsize = 20, color="darkgrey")

        # customize grid
        ax.grid(True, color='darkgrey',  linestyle='-.', linewidth=0.7)


    def plotLiftDragOverLiftOptimizationPoints(self, ax, polar):
        print("plotting CL/CD over CL target-op-points for Re = %.0f...\n"\
              % (polar.Re))

        # check if there are operationg-conditions available
        if (polar.operatingConditions == None):
            return
        else:
            operatingConditions =polar.operatingConditions
            numOpPoints = len(operatingConditions["op_point"])

        for idx in range(numOpPoints):
            # get op-mode and -type
            op_mode = operatingConditions["op_mode"][idx]
            op_type = operatingConditions["optimization_type"][idx]
            op_name = operatingConditions["name"][idx]

            if (op_mode == 'spec-cl') and (op_type != 'min-glide-slope'):
                # get CL
                x = operatingConditions["op_point"][idx]

                # get CD from target-value
                Cd = operatingConditions["target_value"][idx]

                # calculate Cl/Cd
                y = x/Cd

                print("target-op-point[%d] \'%s\', CL/CD: %f, CL:%f" % (idx, op_name, x, y))

                # plot
                ax.plot(x, y, 'y.')

        print("Done.\n\n")


    def plotLiftDragOverLiftPolar(self, ax, polars):
        # set axes and labels
        self.setAxesAndLabels(ax, 'Cl/Cd, Cl', 'Cl', 'Cl/Cd')

        # get polar of root-airfoil
        rootPolar = polars[0]

        # set y-axis manually
        ax.set_ylim(min(rootPolar.CL_CD) - 10, max(rootPolar.CL_CD) + 10)

        # all polars
        for polar in polars:

            if (polar == rootPolar):
                T1_label = 'T1-polar'
                T2_label = 'T2-polar'
            else:
                T1_label = None
                T2_label = None

            # determine idx for changing colors
            switchIdx = polar.T2_T1_switchIdx

            # plot lower (T1)-part of polar
            x = polar.CL[0:switchIdx+1]
            y = polar.CL_CD[0:switchIdx+1]
            # plot CL, CD
            ax.plot(x, y, (cl_T1_polar+'-'), label=T1_label)

            # plot upper (T2)-part of polar
            x = polar.CL[switchIdx:len(polar.CD)]
            y = polar.CL_CD[switchIdx:len(polar.CL)]
            # plot CL, CD
            ax.plot(x, y, (cl_T2_polar+'-'), label=T2_label)
            ax.legend(loc='upper left')

            # plot max_speed
            x = polar.CL[polar.maxSpeed_idx]
            y = polar.CL_CD[polar.maxSpeed_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # add text for root Polar only
            if (polar == rootPolar):
                ax.annotate('maxSpeed (root) @ Cl = %.2f, Cl/Cd = %.2f' % (x, y), xy=(x,y),
                   xytext=(20,0), textcoords='offset points', fontsize = fs_infotext, color=cl_infotext)

            # plot max_glide
            x = polar.CL[polar.maxGlide_idx]
            y = polar.CL_CD[polar.maxGlide_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # add text for root Polar only
            if (polar == rootPolar):
                ax.annotate('maxGlide (root) @ Cl = %.2f, Cl/Cd = %.2f' % (x, y), xy=(x,y),
                   xytext=(10,10), textcoords='offset points', fontsize = fs_infotext, color=cl_infotext)

            # plot max Lift
            x = polar.CL[polar.maxLift_idx]
            y = polar.CL_CD[polar.maxLift_idx]
            ax.plot(x, y, 'o', color=cl_infotext)
            # add text for root Polar only
            if (polar == rootPolar):
                ax.annotate('maxLift (root) @ Cl = %.2f, Cl/Cd = %.2f' % (x, y), xy=(x,y),
                   xytext=(10,10), textcoords='offset points', fontsize = fs_infotext, color=cl_infotext)

            # plot optimizationPoints
            self.plotLiftDragOverLiftOptimizationPoints(ax, polar)


    def draw(self, scriptDir, params):
        # get polars
        polars = params.merged_polars

        # get polar of root-airfoil
        rootPolar = polars[0]

        print("plotting polar of airfoil %s at Re = %.0f..."
                       % (rootPolar.airfoilname, rootPolar.Re))

        # set 'dark' style
        plt.style.use('dark_background')

        # setup subplots
        fig, (upper,lower) = plt.subplots(2,2)

        # compose diagram-title
        text = ("Analysis of airfoil \"%s\" at " % rootPolar.airfoilname)

        if (rootPolar.polarType == 2):
            text = text + "ReSqrt(Cl) = "
            polarType = '1/2'
        else:
            text = text + "Re = "
            polarType = '1'

        # add Re-numbers
        for polar in polars:
            text = text + ("%d, " %polar.Re)

        text = text + ("Type %s polars" % polarType)

        fig.suptitle(text, fontsize = 20, color="darkgrey", **csfont)

        # first figure, display strak-machine-logo
        self.plotLogo(upper[0], scriptDir)

        # second figure, display the Lift / Drag-Polar
        self.plotLiftDragPolar(lower[0], polars)

        # third figure, display the Lift / alpha-Polar
        self.plotLiftOverAlphaPolar(upper[1], polars)

        # fourth figure, display the lift/drag /Lift polar
        self.plotLiftDragOverLiftPolar(lower[1], polars)

        # maximize window
        figManager = plt.get_current_fig_manager()
        figManager.window.showMaximized()

        # show diagram
        plt.show()


################################################################################
#
# polarData class
#
################################################################################
class polarData:
    def __init__(self):
        self.polarName = ''
        self.airfoilname = "airfoil"
        self.polarType = 2
        self.Re = 0
        self.maxRe = 0
        self.NCrit = 9.0
        self.alpha = []
        self.CL = []
        self.CD = []
        self.CL_CD = []
        self.CDp = []
        self.Cm = []
        self.Top_Xtr = []
        self.Bot_Xtr= []
        self.CD_maxSpeed = 0.0
        self.CL_maxSpeed = 0.0
        self.maxSpeed_idx = 0
        self.CL_CD_max = 0.0
        self.maxGlide_idx = 0
        self.alpha_maxGlide= 0.0
        self.CL_maxGlide = 0.0
        self.CL_maxLift = 0.0
        self.alpha_maxLift = 0.0
        self.maxLift_idx = 0
        self.pre_CL_maxLift = 0.0
        self.pre_maxLift_idx = 0
        self.pre_alpha_maxLift = 0.0
        self.operatingConditions = None
        self.Cl_switchpoint_Type2_Type1_polar = 999999
        self.T2_T1_switchIdx = 0

    def addOperatingConditions(self, opConditions):
        self.operatingConditions = opConditions.copy()

    def importFromFile(self, fileName):
        BeginOfDataSectionTag = "-------"
        airfoilNameTag = "Calculated polar for:"
        ReTag = "Re ="
        parseInDataPoints = 0
        print("importing polar %s...\n" %fileName)

        # open file
        fileHandle = open(fileName)

        # parse all lines
        for line in fileHandle:

            # scan for airfoil-name
            if  line.find(airfoilNameTag) >= 0:
                splitline = line.split(airfoilNameTag)
                self.airfoilname = splitline[1]
                self.airfoilname = self.airfoilname.strip()

           # scan for Re-Number
            if  line.find(ReTag) >= 0:
                splitline = line.split(ReTag)
                splitline = splitline[1].split("Ncrit")
                Re_string = splitline[0].strip()
                splitstring = Re_string.split("e")
                faktor = float(splitstring[0].strip())
                Exponent = float(splitstring[1].strip())
                self.Re = faktor * (10**Exponent)
                self.airfoilname = self.airfoilname.strip()

            # scan for start of data-section
            if line.find(BeginOfDataSectionTag) >= 0:
                parseInDataPoints = 1
            else:
                # get all Data-points from this line
                if parseInDataPoints == 1:
                    splittedLine = line.split("  ")
                    self.alpha.append(float(splittedLine[1]))
                    self.CL.append(float(splittedLine[2]))
                    self.CD.append(float(splittedLine[3]))
                    CL_CD = float(splittedLine[2])/float(splittedLine[3])
                    self.CL_CD.append(CL_CD)
                    self.CDp.append(float(splittedLine[4]))
                    self.Cm.append(float(splittedLine[5]))
                    self.Top_Xtr.append(float(splittedLine[6]))
                    self.Bot_Xtr.append(float(splittedLine[7]))

        fileHandle.close()
        print("done.\n")


    def merge(self, mergePolar_1, switching_Cl, maxRe):
        print ("merging polars at Cl = %s.." % switching_Cl)

        # create a new, empty polar
        mergedPolar = polarData()

        # copy some information form mergePolar_1
        mergedPolar.airfoilname = self.airfoilname
        mergedPolar.polarType = self.polarType
        mergedPolar.Re = self.Re
        mergedPolar.NCrit = self.NCrit
        mergedPolar.Cl_switchpoint_Type2_Type1_polar = switching_Cl
        mergedPolar.maxRe = maxRe

        # merge first polar from start Cl to switching_Cl
        for idx in range(len(mergePolar_1.CL)):
            if (mergePolar_1.CL[idx] <= switching_Cl):
                mergedPolar.alpha.append(mergePolar_1.alpha[idx])
                mergedPolar.CL.append(mergePolar_1.CL[idx])
                mergedPolar.CD.append(mergePolar_1.CD[idx])
                mergedPolar.CL_CD.append(mergePolar_1.CL_CD[idx])
                mergedPolar.CDp.append(mergePolar_1.CDp[idx])
                mergedPolar.Cm.append(mergePolar_1.Cm[idx])
                mergedPolar.Top_Xtr.append(mergePolar_1.Top_Xtr[idx])
                mergedPolar.Bot_Xtr.append(mergePolar_1.Bot_Xtr[idx])
                mergedPolar.T2_T1_switchIdx = idx

        # merge second polar from switching_Cl to end Cl
        for idx in range(len(self.CL)):
            if (self.CL[idx] > switching_Cl):
                mergedPolar.alpha.append(self.alpha[idx])
                mergedPolar.CL.append(self.CL[idx])
                mergedPolar.CD.append(self.CD[idx])
                mergedPolar.CL_CD.append(self.CL_CD[idx])
                mergedPolar.CDp.append(self.CDp[idx])
                mergedPolar.Cm.append(self.Cm[idx])
                mergedPolar.Top_Xtr.append(self.Top_Xtr[idx])
                mergedPolar.Bot_Xtr.append(self.Bot_Xtr[idx])

        print("done.\n")
        return mergedPolar


    def determineMaxSpeed(self):
        self.CL_maxSpeed = 0.0
        self.CD_maxSpeed = 1000000.0
        self.maxSpeed_idx = 0

        # find absolute minimum of Cd
        for idx in range(len(self.CD)):
            if (self.CD[idx] < self.CD_maxSpeed):
                self.CD_maxSpeed = self.CD[idx]
                self.CL_maxSpeed = self.CL[idx]
                self.maxSpeed_idx = idx
        print("max Speed, Cd = %f @ Cl = %f" %
                                  (self.CD_maxSpeed, self.CL_maxSpeed))


    def determineMaxGlide(self):
        # determine max-value for Cl/Cd (max glide) and corresponding Cl
        peak_height = 2.0
        self.maxGlide_idx = findPeak(self.CL_CD, peak_height)
        self.CL_maxGlide = self.CL[self.maxGlide_idx]
        self.alpha_maxGlide = self.alpha[self.maxGlide_idx]
        self.CL_CD_max = self.CL_CD[self.maxGlide_idx]

        print("max Glide, Cl/Cd = %f @ Cl = %f" %
                                  (self.CL_CD_max, self.CL_maxGlide))


    def determineMaxLift(self):
        # determine max lift-value and corresponding alpha
        peak_height = 0.025
        self.maxLift_idx = findPeak(self.CL, peak_height)
        self.CL_maxLift = self.CL[self.maxLift_idx]
        self.alpha_maxLift = self.alpha[self.maxLift_idx]

        # also calculate opPoint before MaxLift that can be reached by the
        # optimizer
        self.pre_CL_maxLift = self.CL_maxLift * 0.99
        self.pre_maxLift_idx = self.find_index(self.pre_CL_maxLift)
        self.pre_alpha_maxLift = self.alpha[self.pre_maxLift_idx]

        print("max Lift, Cl = %f @ alpha = %f" %
                                  (self.CL_maxLift, self.alpha_maxLift))


    def analyze(self):
        # yy_sg = savgol_filter(itp(xx), window_size, poly_order) TODO smoothing
        print("analysing polar...")
        self.determineMaxSpeed()
        self.determineMaxGlide()
        self.determineMaxLift()
        print("done.\n")


    def find_CD(self, CL):
        # calculate corresponding CD
        # reduce list of CL, CD-values up to CL_max. No duplicate CL-values are
        # allowed!
        x = []
        y = []
        for i in range(self.maxLift_idx):
            x.append(self.CL[i])
            y.append(self.CD[i])

        #double append the last value
        x.append(self.CL[i])
        y.append(self.CD[i])

        # interpolate the values
        CD = np.interp( CL, x, y)
        return CD

    def find_index(self, CL):
        for i in range(len(self.CL)):
            if (self.CL[i] >= CL):
                return i
        return 0

    def find_CL(self, alpha):
        for i in range(len(self.alpha)):
            if (self.alpha[i] >= alpha):
                return self.CL[i]


    def find_CL_CD(self, CL):
        # calculate corresponding CL_CD
        # reduce list of CL, CL_CD-values up to CL_max. No duplicate CL-values are
        # allowed!
        x = []
        y = []
        for i in range(self.maxLift_idx):
            x.append(self.CL[i])
            y.append(self.CL_CD[i])

        #double append the last value
        x.append(self.CL[i])
        y.append(self.CL_CD[i])

        # interpolate the values
        CL_CD = np.interp(CL, x, y)
        return CL_CD



################################################################################
# Input function that checks python version
def my_input(message):

  # Check python version

  python_version = version_info[0]

  # Issue correct input command

  if (python_version == 2):
    return raw_input(message)
  else:
    return input(message)


################################################################################
# function that gets the name of the wing
def get_wingName(wing):
    for name in wing.iter('Name'):
        return name.text

    # name was not found, return default-name
    return 'wing'


################################################################################
# function, that gets the chord-length of a section
def get_chordFromSection(section):
    # create an empty list
    chordList = []

    # iterate through elements
    for chord in section.iter('Chord'):
        # convert text to float
        chordlength = float(chord.text.strip("\r\n\t '"))

        #append chordlength to list
        chordList.append(chordlength)

    return chordList


################################################################################
# function that gets the airfoil-name of a section
def get_airfoilNameFromSection(section):
    # create an empty list
    airfoilNameList = []

    # iterate through elements
    for airfoilName in section.iter('Left_Side_FoilName'):

        #append airfoilName to list
        airfoilNameList.append(airfoilName.text)

    return airfoilNameList


################################################################################
# function that gets the chord-lengths of the wing
def get_wingChords(wing):
    # iterate the elements of the wing
    for section in wing.iter('Sections'):
        return get_chordFromSection(section)


################################################################################
# function that gets the airfoil-names of the wing
def get_airfoilNames(wing):
    # iterate the elements of the wing
    for section in wing.iter('Sections'):
        return get_airfoilNameFromSection(section)


################################################################################
# function that reads plane-data from XFLR5 XML-file
def read_planeDataFile(fileName):

    # init data as an empty list
    data = []

    # parse the file containing XFLR5-plane-data
    tree = ET.parse(fileName)

    #get root of XML-tree
    root = tree.getroot()

    # find wing-data
    for wing in root.iter('wing'):
        # create dictionary containg the wing-data
        wingDict = 	{ 'name': get_wingName(wing),
                      'chordLengths': get_wingChords(wing),
                      'airfoilNames': get_airfoilNames(wing)
                    }

        #append dictionary to data
        data.append(wingDict)

    # debug output
    #print data
    return data


################################################################################
# function that gets the name of an airfoil
def get_FoilName(params, index):

    # is there wingdata available ?
    if (params.wingData != None):
        # yes
        wing = params.wingData
        # get airfoil-names from wing-dictionary
        airfoilNames = wing.get('airfoilNames')
        foilName = airfoilNames[index]
    else:
        # compose foilname with seedfoilname and Re-number
        Re = params.ReNumbers[index]

        if (params.operatingMode == 'matchpolarfoils'):
            foilName = params.matchPolarFoilName
        else:
            foilName = params.seedFoilName

        if (index == 0):
            suffix = '-root'
        else:
            suffix = '-strak'

        foilName = (foilName + "%s-%03dk.dat") % (suffix,(Re/1000))

    return (foilName)

################################################################################
# function that gets the number of chords
def get_NumberOfAirfoils(params):

    # is there wingdata available ?
    if (params.wingData != None):
        # get number of chords from wing-data
        num = len(params.wingData.get('chordLengths'))
    else:
        # get number of chords from ReNumbers
        num = len(params.ReNumbers)

    return num


################################################################################
# function that generates commandlines to run Xoptfoil
def generate_commandlines(params):
    print("Generating commandlines...")

    # create an empty list of commandlines
    commandLines = []

    # do some initializations / set local variables
    if (params.operatingMode != 'matchpolarfoils'):
        rootfoilName = get_FoilName(params, 0)# +'.dat'
        firstIdx = 1
    else:
        rootfoilName = params.seedFoilName# +'.dat'
        firstIdx = 0

    numFoils = get_NumberOfAirfoils(params)#TODO refactor
    ReList = params.get_ReList()

    # change current working dir to output folder
    commandline = "cd %s\n" % params.outputFolder
    commandLines.append(commandline)

    if (params.operatingMode != 'matchpolarfoils'):
        # copy root-foil to airfoil-folder as it can be used
        # as the root airfoil without optimization
        commandline = ("copy %s %s" + bs + "%s\n") % \
        (get_FoilName(params, 0), params.airfoilFolder, get_FoilName(params, 0))
        commandLines.append(commandline)

    # store rootfoilname
    strakFoilName = rootfoilName
    previousFoilname = rootfoilName

    # add command-lines for each strak-airfoil
    # skip the root airfoil (as it was already copied)
    for i in range (firstIdx, numFoils):

        if (params.useAlwaysRootfoil == False):
            # store previous airfoil-name
            previousFoilname = strakFoilName

        # get name of the airfoil
        strakFoilName = get_FoilName(params, i)

        # set input-file name for Xoptfoil
        iFile = params.inputFileNames[i]

        # generate Xoptfoil-commandline
        commandline = "xoptfoil-jx -i %s -r %d -a %s -o %s\n" %\
                        (iFile, ReList[i], previousFoilname + '.dat',
                          strakFoilName.strip('.dat'))
        commandLines.append(commandline)

        #copy strak-airfoil to airfoil-folder
        commandline = ("copy %s %s" + bs +"%s\n") % \
            (strakFoilName , params.airfoilFolder, strakFoilName)
        commandLines.append(commandline)

    # change current working dir back
    commandline = "cd..\n"
    commandLines.append(commandline)

    print("Done.")
    return commandLines, ReList


################################################################################
# function that generates a Xoptfoil-batchfile
def generate_batchfile(batchFileName, commandlines):
    try:
        # create a new file
        outputfile = open(batchFileName, "w+")
    except:
        print ('Error, file %s could not be opened' % batchFileName)
        return

    # write Xoptfoil-commandline to outputfile
    for element in commandlines:
        outputfile.write(element)

    # close the outputfile
    outputfile.close()


def generate_visu_batchfiles(params):
   # determine start-index
    if (params.operatingMode == 'matchpolarfoils'):
        startidx = 0
    else:
        startidx = 1

    for i in range(startidx, len(params.ReNumbers)):
        visuFileName = "visu_%dk.bat" % (params.ReNumbers[i]/1000)
        airfoilName = get_FoilName(params, i)
        airfoilName = airfoilName.strip('.dat')

        try:
            # create a new file
            outputfile = open(visuFileName, "w+")
        except:
            print ('Error, file %s could not be opened' % visuFileName)
            return

        # write commandlines
        outputfile.write("cd build\n")
        outputfile.write("xoptfoil_visualizer-jx.py -o 3 -c %s\n" % airfoilName)

        # close the outputfile
        outputfile.close()

################################################################################
# function that gets the name of the strak-machine-data-file
def getInFileName(args):

    if args.input:
        inFileName = args.input
    else:
        # use Default-name
        inFileName = 'ressources/strakdata'

    inFileName = inFileName + '.txt'
    print("filename for strak-machine input-data is: %s" % inFileName)
    return inFileName


################################################################################
# function that gets arguments from the commandline
def getArguments():

    # initiate the parser
    parser = argparse.ArgumentParser('')

    parser.add_argument("-input", "-i", help="filename of strak-machine input"\
                        "-file (e.g. strak_data)")

    # read arguments from the command line
    args = parser.parse_args()
    return (getInFileName(args))


################################################################################
# function that gets parameters from dictionary
def getParameters(dict):

    params = strakData()

    try:
        params.inputFolder = dict["inputFolder"]
    except:
        print ('inputFolder not specified, assuming no input-folder shall be used.')

    try:
        params.outputFolder = dict["outputFolder"]
    except:
        print ('outputFolder not specified, assuming no output-folder shall be used.')

    try:
        params.batchfileName = dict["batchfileName"]
    except:
        print ('batchfileName not found, setting default-filename \'%s\'.'\
                % params.batchfileName)

    try:
        params.xmlFileName = dict["XMLfileName"]
    except:
        print ('XMLfileName not specified, assuming no xml-file shall be used.')

    try:
        params.strakInputFileName = dict["strakInputFileName"]
    except:
        print ('strakInputFileName not found, setting default-filename \'%s\'.'\
                % params.strakInputFileName)

    try:
        params.ReNumbers = dict["ReNumbers"]
    except:
        print ('ReNumbers not specified, using no list of ReNumbers')

    try:
        params.maxReFactor = dict["maxReFactor"]
    except:
        print ('maxReFactor not specified, using default-value %f'
                 % params.maxReFactor)

    try:
        params.seedFoilName = dict["seedFoilName"]
    except:
        print ('seedFoilName not specified')

    try:
        params.strakType = dict["strakType"]
    except:
        print ('strakType not specified')

    try:
        params.operatingMode = dict["operatingMode"]
    except:
        print ('operatingMode not specified')

    # get matchpolarfoilname only, if operating-mode is set to "matchpolarfoils"
    if (params.operatingMode == 'matchpolarfoils'):
        try:
            params.matchPolarFoilName = dict["matchPolarFoilName"]
            params.useAlwaysRootfoil = True
        except:
            print ('matchPolarFoilName not specified')
    else:
        try:
            if (dict["useAlwaysRootfoil"] == 'true'):
                params.useAlwaysRootfoil = True
            else:
                params.useAlwaysRootfoil = False
        except:
            print ('useAlwaysRootfoil not specified')

    try:
        if (dict["adaptInitialPerturb"] == 'true'):
            params.adaptInitialPerturb = True
        else:
            params.adaptInitialPerturb = False
    except:
        print ('adaptInitialPerturb not specified')

    try:
        if (dict["weighting_mode"] == 'linear_progression'):
            params.weighting_mode = 'linear_progression'
        else:
            params.weighting_mode = 'constant'
    except:
        print ('weighting_mode not specified')

    try:
        if (dict["skipPolarGeneration"] == 'true'):
            params.skipPolarGeneration = True
        else:
            params.skipPolarGeneration = False
    except:
        print ('skipPolarGeneration not specified')

    try:
        if (dict["smoothSeedfoil"] == 'true'):
            params.smoothSeedfoil = True
        else:
            params.smoothSeedfoil = False
    except:
        print ('smoothSeedfoil not specified')

    try:
        if (dict["smoothMatchPolarFoil"] == 'true'):
            params.smoothMatchPolarFoil = True
        else:
            params.smoothMatchPolarFoil = False
    except:
        print ('smoothMatchPolarFoil not specified')

    try:
        params.maxGlideLoss = dict["maxGlideLoss"]
    except:
        print ('maxGlideLoss not specified')

    try:
        params.maxSpeedGain = dict["maxSpeedGain"]
    except:
        print ('maxSpeedGain not specified')

    try:
        params.maxLiftGain = dict["maxLiftGain"]
    except:
        print ('maxLiftGain not specified')

    try:
        params.numOpPoints = dict["numOpPoints"]
        if (params.numOpPoints < 5):
            params.numOpPoints = 5
    except:
        print ('numOpPoints not specified')

    try:
        params.Cl_min = dict["Cl_min"]
    except:
        print ('Cl_min not specified')

    return params


def getListOfFiles(dirName):
    # create a list of files in the given directory
    listOfFile = os.listdir(dirName)
    allFiles = list()

    # Iterate over all the entries
    for entry in listOfFile:
        # Create full path
        fullPath = os.path.join(dirName, entry)
        allFiles.append(fullPath)

    return allFiles


def getwingDataFromXML(params):

    xmlFileName = params.inputFolder + '/' + params.xmlFileName
    try:
        planeData = read_planeDataFile(xmlFileName)
    except:
        print("Error, file \"%s\" could not be opened.") % xmlFileName
        exit(-1)

    # return data
    return planeData[0]


def copyAndSmoothAirfoil(srcName, srcPath, destName, smooth):
    srcfoilNameAndPath = srcPath + bs + srcName + '.dat'

    if (smooth):
        print("Smoothing airfoil \'%s\', creating airfoil \'%s\'\n" %\
                       (srcName, destName))
        # smooth, rename and copy the airfoil
        inputFilename = getPresetInputFileName('Smooth')

        # compose system-string for smoothing the seed-airfoil
        systemString = "xfoil_worker.exe -w smooth -i %s -a %s -o %s" % \
                       (inputFilename, srcfoilNameAndPath, destName)

        # execute xfoil-worker / create the smootehed root-airfoil
        os.system(systemString)
    else:
        print("Renaming airfoil \'%s\' to \'%s\'\n" % (srcName, destName))
        # only reanme and copy the airfoil
        systemString = "change_airfoilname.py -i %s -o %s" %\
                              (srcfoilNameAndPath, destName + '.dat')
        os.system(systemString)

    print("Done.")


def copy_matchpolarfoils(params):
    # get the name of the matchfoil
    matchfoilName = params.matchPolarFoilName

    # get name of seed-airfoil
    seedFoilName = params.seedFoilName

    # get the path where the airfoil can be found
    srcPath = ".." + bs + params.inputFolder

    # copy and smooth the matchfoil
    copyAndSmoothAirfoil(matchfoilName, srcPath, matchfoilName,
                                             params.smoothMatchPolarFoil)

    # copy and smooth the seedfoil
    copyAndSmoothAirfoil(seedFoilName, srcPath, seedFoilName,
                                             params.smoothSeedfoil)

    print("Done.")
    return matchfoilName


def generate_rootfoil(params):
    # get name of seed-airfoil
    seedFoilName = params.seedFoilName

    # get name of root-airfoil
    rootfoilName = get_FoilName(params, 0).strip('.dat')

    # get the path where the seed-airfoil can be found
    srcPath = ".." + bs + params.inputFolder

    # copy and smooth the airfoil, also rename
    copyAndSmoothAirfoil(seedFoilName, srcPath, rootfoilName,
                                           params.smoothSeedfoil)

    return rootfoilName


def generate_inputFiles(params):
    print("Generating inputfiles...")

    # get root-polar
    rootPolar = params.merged_polars[0]
    num_polars = len(params.ReNumbers)

    # generate files for all Re-numbers
    for i in range(num_polars):
        # get strak-polar
        strakPolar = params.merged_polars[i]

        # create new inputfile
        newFile = inputFile(params.strakType)

        # generate a fresh list of equally distributed op-Points
        newFile.generateOpPoints(params.numOpPoints, params.Cl_min,
                               rootPolar.CL_maxLift, rootPolar.alpha_maxLift)

        # distribute main opPoints, taking the analysed data of the root-polar
        newFile.distributeMainOpPoints(rootPolar.CL_maxSpeed,
         rootPolar.CL_maxGlide, rootPolar.pre_CL_maxLift,
         rootPolar.pre_alpha_maxLift, rootPolar.CL_maxLift,
         rootPolar.alpha_maxLift)

        # now distribute the opPoints between the main opPoints equally
        newFile.distributeIntermediateOpPoints(rootPolar)
        #newFile.printOpPoints()#debug

        # set the importance / weightings of the op-points
        newFile.SetWeightings(params)

        if (params.operatingMode == 'matchpolarfoils'):
          # adapt op-points according to polar of match-polar-foil
            newFile.adaptAllOppointsToPolar(strakPolar)
            #newFile.printOpPoints()#Debug
        else:
            # as a first step always adapt op-points according to polar of
            # root-airfoil
            newFile.adaptAllOppointsToPolar(rootPolar)

            # as a second step,change oppoints again, but only "shift" them
            # matching the polar of the strak-airfoil
            newFile.transferOppointsKeepShape(params, params.merged_polars[i])

        if params.adaptInitialPerturb:
            # also adapt the initial perturb according to the change in
            # Re-number
            if (params.useAlwaysRootfoil):
                # difference always calculated to Re-number of root-airfoil
                ReDiff = params.ReNumbers[0] - params.ReNumbers[i]
            else:
                # difference calculated to Re-number of previous-airfoil
                ReDiff = params.ReNumbers[i-1] - params.ReNumbers[i]

            newFile.setInitialPerturb(ReDiff)

        # copy operating-conditions to polar, so they can be plotted in the graph
        opConditions = newFile.getOperatingConditions()
        strakPolar.addOperatingConditions(opConditions)

        # physically create the file
        newFile.writeToFile(params.inputFileNames[i])

    print("Done.")


def generate_polars(params, workingDir, rootfoilName):
# generate polars of seedfoil / root-airfoil:
    print("Generating polars for airfoil %s..." % rootfoilName)

    # compose polar-dir
    polarDir = workingDir + bs + rootfoilName + '_polars'

    # create polars, polar-file-Names and input-file-names from Re-Numbers
    for ReIdx in range(len(params.ReNumbers)):
        # get Re, maxRe
        Re = params.ReNumbers[ReIdx]
        maxRe = params.maxReNumbers[ReIdx]

        # create polar-file-Name T1-polar from maxRe-Number
        polarFileName_T1 = "T1_Re0.%03d_M0.00_N9.0.txt" % (maxRe/1000)
        polarFileNameAndPath_T1 = polarDir + bs + polarFileName_T1
        params.polarFileNames_T1.append(polarFileNameAndPath_T1)

        # create polar-file-Name T2-polar from Re-Number
        polarFileName_T2 = "T2_Re0.%03d_M0.00_N9.0.txt" % (Re/1000)
        polarFileNameAndPath_T2 = polarDir + bs + polarFileName_T2
        params.polarFileNames_T2.append(polarFileNameAndPath_T2)

        # generate inputfilename from Re-number
        inputFilename = params.strakInputFileName.strip('.txt')
        inputFilename = inputFilename + ("_%03dk.txt" % (Re/1000))
        params.inputFileNames.append(inputFilename)

        # compose string for system-call of XFOIL-worker for T1-polar generation
        airfoilName = rootfoilName + '.dat'
        inputFilename = getPresetInputFileName(T1_polarInputFile)
        systemString_T1 = "xfoil_worker.exe -i \"%s\" -o \"%s\" -w polar -a \"%s\" -r %d" %\
                              (inputFilename, rootfoilName, airfoilName, maxRe)

        # compose string for system-call of XFOIL-worker for T2-polar generation
        inputFilename = getPresetInputFileName(T2_polarInputFile)
        systemString_T2 = "xfoil_worker.exe -i \"%s\" -o \"%s\" -w polar -a \"%s\" -r %d" %\
                                 (inputFilename, rootfoilName, airfoilName, Re)

        # execute xfoil-worker / create T1 / T2 polar-files
        if (not params.skipPolarGeneration):
            print("Generating polar %s" % polarFileName_T1)
            os.system(systemString_T1)

            print("Generating polar %s" % polarFileName_T2)
            os.system(systemString_T2)

        # import polar type 1
        newPolar_T1 = polarData()
        newPolar_T1.importFromFile(polarFileNameAndPath_T1)
        params.T1_polars.append(newPolar_T1)

        # import polar type 2
        newPolar_T2 = polarData()
        newPolar_T2.importFromFile(polarFileNameAndPath_T2)
        params.T1_polars.append(newPolar_T2)

        # merge T1/T2 polars at Cl switching-point
        mergedPolar = newPolar_T2.merge(newPolar_T1,
                         params.Cl_switchpoint_Type2_Type1_polar, maxRe)

        # analyze merged polar
        mergedPolar.analyze()

        # set name
        mergedPolar.polarName = 'mergedPolar T1/T2, ReSqrt(Cl) = %.0f, Re = %0.f' %\
                (newPolar_T2.Re, newPolar_T1.Re)

        # add merged polar to params
        params.merged_polars.append(mergedPolar)

    print("Done.")

################################################################################
# Main program
if __name__ == "__main__":

    # get command-line-arguments or user-input
    strakDataFileName = getArguments()

    # get real path of the script
    pathname = os.path.dirname(sys.argv[0])
    scriptPath = os.path.abspath(pathname)

##    #debug
##    out_file = open("strakdata.txt",'w')
##    json.dump(strakdata, out_file, indent = 6)
##    out_file.close()

    # try to open .json-file
    try:
        strakDataFile = open(strakDataFileName)
    except:
        print('Error, failed to open file %s' % strakDataFileName)
        exit(-1)

    # load dictionary from .json-file
    try:
        strakdata = json.load(strakDataFile)
        strakDataFile.close()
    except:
        print('Error, failed to read data from file %s' % strakDataFileName)
        strakDataFile.close()
        exit(-1)

    # get strak-machine-parameters from dictionary
    params = getParameters(strakdata)

    # read plane-data from XML-File, if requested //TODO: only wing-data
    if (params.xmlFileName != None):
        params.wingData = getwingDataFromXML(params)

    # calculate further values like max Re-numbers etc.
    params.calculateDependendValues()

    # compose name of the folder, where the airfoils shall be stored
    params.airfoilFolder = 'airfoils'

    # get current working dir
    workingDir = os.getcwd()

    # check if output-folder exists. If not, create folder.
    if not os.path.exists(params.outputFolder):
        os.makedirs(params.outputFolder)

    # check if airfoil-folder exists. If not, create folder.
    if not os.path.exists(params.outputFolder + '\\' + params.airfoilFolder):
        os.makedirs(params.outputFolder + '\\' + params.airfoilFolder)

    # create an instance of polar graph
    graph = polarGraph()

    # change working-directory
    os.chdir(workingDir + bs + params.outputFolder)

    # get current working dir again
    workingDir = os.getcwd()

    # get name of root-airfoil according to operating-mode
    if (params.operatingMode == 'matchpolarfoils'):
        rootfoilName = copy_matchpolarfoils(params)
    else:
        rootfoilName = generate_rootfoil(params)

    # generate polars of root-airfoil, also analyze
    generate_polars(params, workingDir, rootfoilName)

    # generate input-Files
    generate_inputFiles(params)

    # generate Xoptfoil command-lines
    commandlines, ReList = generate_commandlines(params)

    # change working-directory
    os.chdir(".." + bs)

    # generate batchfile
    print("Generating batchfile...")
    if (params.generateBatch == True):
        print ('generating batchfile \'%s\'' % params.batchfileName)
        generate_batchfile(params.batchfileName, commandlines)
        print ('generating visu-batchfiles')
        generate_visu_batchfiles(params)
    print("Done.")

    # show graph
    graph.draw(scriptPath, params)

    print("Ready.")
