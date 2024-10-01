from flask import Flask, render_template, request
from waitress import serve
#from dotenv import load_dotenv
import os
import sys
import requests
import json
# import rrdtool
import threading
# import time
# import datetime

app = Flask(__name__)

gFreePowerSave = 0
gFreePower = 0
gManual = False
gBackgroundLoop = True
gDebug = 0
gCurrent = 0 
gPause = 0
gLimit = 0
gPhase = 0

minimalPower   = 1440 # 6 * 240 
maximalPowerP1 = 2880 # 12 * 240
minimalPowerP2 = 2880 # 6 * 240 * 2
maximalPowerP2 = 5760 # 12 * 240 * 2
minimalPowerP3 = 4320 # 6 * 240 * 3
maximalPowerP3 = 8640 # 12 * 240 * 3

NRGkick = 'http://nrgkick.i.pmei.ch'
SolarWatt = 'http://kiwigrid.i.pmei.ch/rest/kiwigrid/wizard/devices'

waitFlag = threading.Event()

def printdebug(level=0,message=''):

    global gDebug

    if level <= gDebug:
        print(message)
 
def fetchJsonData(url):
    try:
        response = requests.get(url)
    except OSError:
        printdebug(0,'No connection to the server!')
        return None

    # check if the request is successful
    if response.status_code == 200:
        printdebug(1,'Status 200, OK')
        return response.json()
    else:
        printdebug(0,f'JSON data request not successful!. {url}')
        return None

def getLocation(jsonContent=None):
    retValue = ""
    if jsonContent is not None:
        for i in jsonContent['result']['items']:
            for x in i['deviceModel']:
                if x['deviceClass'] == 'com.kiwigrid.devices.location.Location':
                    retValue = i['guid']

    return retValue

def getItem(jsonContent=None, itemGuid=""):
    retValue = None
    if jsonContent is not None:
        for i in jsonContent['result']['items']:
            if  i['guid'] == itemGuid:
                retValue = i
                break

    return retValue

def getFreePower(url=''):

    freePower = 0
    # get file from device
    json_file_content = fetchJsonData(url)

    # get value out from json
    if json_file_content is not None:
        for item in json_file_content['result']['items']:
            if item['tagValues']['IdName']['value'] == 'Haus':
                freePower = item['tagValues']['PowerOut']['value']

    return freePower - 500

def sendNRGkick(aurl=''):

    control = fetchJsonData(NRGkick + aurl)

    printdebug(1,control)

    return control

def switchPhase(freePower=0):

    if freePower >= minimalPowerP3:
        freeA = round( freePower / 240 / 3, 1)
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=3&charge_pause=0')
        
    elif freePower >= minimalPowerP2:
        freeA = round( freePower / 240 / 2, 1)
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=2&charge_pause=0')

    elif freePower >= minimalPower:
        freeA = round( freePower / 240 / 1, 1)
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=1&charge_pause=0')

    else:    
        freeA = round( freePower / 240 / 3, 1)
        control = sendNRGkick(f'/control?charge_pause=1')

    return control

def setNRGkick(freePower=0, manual=False):
    
    global gCurrent
    global gPause
    global gLimit
    global gPhase

    if manual:
        printdebug(1,'manual Mode')        
        control = switchPhase(maximalPowerP3)

    else:
        control = sendNRGkick('/values?powerflow')
        if control is not None:
            allreadyUsed = control['powerflow']['total_active_power']
            freePower += allreadyUsed

        control = sendNRGkick('/control')
        if control is not None:
            
            if control['charge_pause'] == 1:
                control = switchPhase(freePower)
            
            elif control['phase_count'] == 1:

                if freePower < minimalPower:
                    control = switchPhase(freePower)

                elif freePower > maximalPowerP1:
                    control = switchPhase(freePower)

                else:        
                    freeA = round( freePower / 240, 1)
                    control = sendNRGkick(f'/control?current_set={str(freeA)}')
            
            elif control['phase_count'] == 2:    

                if freePower < minimalPowerP2:
                    control = switchPhase(freePower)

                elif freePower > maximalPowerP2:
                    control = switchPhase(freePower)

                else:        
                    freeA = round( freePower / 240 / 2, 1)
                    control = sendNRGkick(f'/control?current_set={str(freeA)}')

            elif control['phase_count'] == 3:    

                if freePower < minimalPowerP3:
                    control = switchPhase(freePower)

                elif freePower >= maximalPowerP3:
                    control = sendNRGkick(f'/control?current_set={12}')

                else:        
                    freeA = round( freePower / 240 / 3, 1)
                    control = sendNRGkick(f'/control?current_set={str(freeA)}')

    control = sendNRGkick('/control')
    if control is not None:
        gCurrent = control['current_set']
        gPause   = control['charge_pause']
        gLimit   = control['energy_limit']
        gPhase   = control['phase_count']
            
    printdebug(0,f'Free Power {freePower} Control {control}')

def backgroundTask(loop=True):

    global gBackgroundLoop
    global gFreePowerSave
    global gFreePower
    global gManual

    gBackgroundLoop = loop
    
    while True:
        # get tha actual value
        freePower = round(getFreePower(SolarWatt), 1)

        # use freePowerSave to get sone everage
        if gFreePowerSave == 0:
            gFreePowerSave = freePower

        gFreePower = round(( freePower + gFreePowerSave ) / 2, 1)
        printdebug(0, f'free {freePower} save {gFreePowerSave} freePower everage is: {gFreePower}')

        setNRGkick(gFreePower, gManual)

        waitFlag.clear()

        if gBackgroundLoop:
            waitFlag.wait(timeout=300)

        else:
            break

        gFreePowerSave = gFreePower

# end backgroundTask

# backgroundTask(False)

curr_thread = threading.Thread(target=backgroundTask, args=())
curr_thread.daemon = False
curr_thread.start()

print('curr_thread',curr_thread)

# time.sleep(3600)

@app.route('/')
@app.route('/index')
def index():

    global gCurrent
    global gPause
    global gLimit
    global gPhase

    return render_template('index.html',
                           debug = gDebug,
                           freePower = gFreePower,
                           freePowerSave = gFreePowerSave,
                           manual = gManual,
                           current = gCurrent,
                           pause = gPause,
                           limit = gLimit,
                           phase = gPhase,
                           timeout=60
    )                   

@app.route('/set_manual')
def set_manual():

    global gManual

    gManual = not gManual

    waitFlag.set()

    return index()
    
@app.route('/set_debug')
def set_debug():

    global gDebug

    gDebug = not gDebug

    waitFlag.set()

    return index()             

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=8001)
