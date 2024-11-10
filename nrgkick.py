from flask import Flask, render_template, request
from waitress import serve
#from dotenv import load_dotenv
import os
import sys
import requests
import math
import json
# import rrdtool
import threading
import time
# import datetime

app = Flask(__name__)

gFreePowerSave = 0
gFreePower = 0
gSetPower = 0
gBackgroundLoop = True
gManTime = 0
gDebug = 0
gCurrent = 0
gPause = 0
gLimit = 0
gPhase = 0
gPowerOut = 0
gPowerIn = 0
gPowerProduced = 0

gminAmpere = 6
gmaxAmpere = 12
gnominalVolt = 240

gPower = {
    'P1': {
        'min':gminAmpere * gnominalVolt,
        'max':gmaxAmpere * gnominalVolt
    },
    'P2' : {
        # 'min':gminAmpere * gnominalVolt * 2,
        # 'max':gmaxAmpere * gnominalVolt * 2
        'min':(gmaxAmpere * gnominalVolt * 1) + 1,
        'max':(gminAmpere * gnominalVolt * 3) - 1
    },
    'P3' : {
        'min':gminAmpere * gnominalVolt * 3,
        'max':gmaxAmpere * gnominalVolt * 3
    }      
}

NRGkick = 'http://nrgkick.i.pmei.ch'
SolarWatt = 'http://kiwigrid.i.pmei.ch/rest/kiwigrid/wizard/devices'

waitFlag = threading.Event()

# set amprere to power
def setAmpere(max = 12, min = 6):

    global gminAmpere
    global gmaxAmpere
    global gnominalVolt
    global gPower
    
    if max > 16:
        max = 16

    if min < 6:
        min = 6

    gmaxAmpere = max
    gminAmpere = min
    gPower['P1']['min'] = gminAmpere * gnominalVolt #1440 # 6 * 240 
    gPower['P1']['max'] = gmaxAmpere * gnominalVolt #2880 # 12 * 240
    # gPower['P2']['min'] = gminAmpere * gnominalVolt * 2 #2880 # 6 * 240 * 2
    gPower['P2']['min'] = (gmaxAmpere * gnominalVolt * 1) + 1 #2880 # 6 * 240 * 2
    # gPower['P2']['max'] = gmaxAmpere * gnominalVolt * 2 #5760 # 12 * 240 * 2
    gPower['P2']['max'] = (gminAmpere * gnominalVolt * 3) - 1 #5760 # 12 * 240 * 2
    gPower['P3']['min'] = gminAmpere * gnominalVolt * 3 #4320 # 6 * 240 * 3
    gPower['P3']['max'] = gmaxAmpere * gnominalVolt * 3 #8640 # 12 * 240 * 3

# print debug messages
def printdebug(level=0,message=''):

    global gDebug

    if level <= gDebug:
        print(message)

# get Json data from URL
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

# get powervaluese form PV
def getFreePower(url=''):

    PowerOut = 0
    PowerIn = 0
    PowerProduced = 0

    # get file from device
    json_file_content = fetchJsonData(url)

    # get value out from json
    if json_file_content is not None:
        for item in json_file_content['result']['items']:
            if item['tagValues']['IdName']['value'] == 'Haus':
                PowerOut = item['tagValues']['PowerOut']['value']
                PowerIn  = item['tagValues']['PowerIn']['value']
                PowerProduced = item['tagValues']['PowerProduced']['value']

    return PowerOut, PowerIn, PowerProduced

def sendNRGkick(aurl=''):

    control = fetchJsonData(NRGkick + aurl)

    printdebug(1,control)

    return control

def switchPhase(freePower=0):

    global gPause

    if freePower >= gPower['P3']['min']:
        freeA = round( freePower / gnominalVolt / 3, 1)
        if freeA > gmaxAmpere:
            freeA = gmaxAmpere
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=3&charge_pause=0')
        gPause = 0
        
    elif freePower >= gPower['P2']['min']:
        freeA = round( freePower / gnominalVolt / 2, 1)
        if freeA > gmaxAmpere:
            freeA = gmaxAmpere
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=2&charge_pause=0')
        gPause = 0

    elif freePower >= gPower['P1']['min']:
        freeA = round( freePower / gnominalVolt / 1, 1)
        if freeA > gmaxAmpere:
            freeA = gmaxAmpere
        control = sendNRGkick(f'/control?current_set={str(freeA)}&phase_count=1&charge_pause=0')
        gPause = 0

    else:    
        # freeA = round( freePower / gnominalVolt / 3, 1)
        control = sendNRGkick(f'/control?charge_pause=1')
        gPause = 1

    return control

def setNRGkick(freePower=0):
    
    global gCurrent
    global gPause
    global gLimit
    global gPhase
    global gManTime

    if gManTime > time.time():
        printdebug(1,'manual Mode')
        control = switchPhase(gPower['P3']['max'])
        freePower = gPower['P3']['max']

    else:
        gManTime = 0
        control = sendNRGkick('/values?powerflow')
        if control is not None:
            allreadyUsed = control['powerflow']['total_active_power']
            freePower += allreadyUsed

        control = sendNRGkick('/control')
        if control is not None:
            
            if control['charge_pause'] == 1:
                control = switchPhase(freePower)
            
            elif control['phase_count'] == 1:

                if freePower < gPower['P1']['min']:
                    control = switchPhase(freePower)

                elif freePower > gPower['P1']['max']:
                    control = switchPhase(freePower)

                else:        
                    freeA = round( freePower / gnominalVolt, 1)
                    control = sendNRGkick(f'/control?current_set={str(freeA)}')
            
            elif control['phase_count'] == 2:    

                if freePower < gPower['P2']['min']:
                    control = switchPhase(freePower)

                elif freePower > gPower['P2']['max']:
                    control = switchPhase(freePower)

                else:        
                    freeA = round( freePower / gnominalVolt / 2, 1)
                    control = sendNRGkick(f'/control?current_set={str(freeA)}')

            elif control['phase_count'] == 3:    
                control = switchPhase(freePower)

    control = sendNRGkick('/control')
    if control is not None:
        gCurrent = control['current_set']
        gPause   = control['charge_pause']
        gLimit   = control['energy_limit']
        gPhase   = control['phase_count']
            
    printdebug(0,f'Free Power {freePower} Control {control}')

    return round(freePower, 1)

def backgroundTask(loop=True):

    global gBackgroundLoop
    global gFreePowerSave
    global gFreePower
    global gSetPower
    global gPowerOut
    global gPowerIn
    global gPowerProduced

    gBackgroundLoop = loop
    
    while True:
        # get tha actual value
        gPowerOut, gPowerIn, gPowerProduced = getFreePower(SolarWatt)
        gPowerOut      = round(gPowerOut, 1)
        gPowerIn       = round(gPowerIn, 1)
        gPowerProduced = round(gPowerProduced, 1)
        
        freePower = gPowerOut - 500

        # use freePowerSave to get sone everage
        if gFreePowerSave == 0:
            gFreePowerSave = freePower

        gFreePower = round(( freePower + gFreePowerSave ) / 2, 1)
        printdebug(0, f'free {freePower} save {gFreePowerSave} freePower everage is: {gFreePower}')

        gSetPower = setNRGkick(gFreePower)

        waitFlag.clear()

        if gBackgroundLoop:
            waitFlag.wait(timeout=60)

        else:
            break

        gFreePowerSave = gFreePower

# end backgroundTask

curr_thread = threading.Thread(target=backgroundTask, args=())
curr_thread.daemon = False
curr_thread.start()

print('curr_thread',curr_thread)

# time.sleep(3600)

@app.route('/')
@app.route('/index')
def index():

    aTime = time.time()
    if gManTime > aTime:
        t = gManTime - aTime
        ManTime = f'{int(t/3600)}:{int(math.fmod(t,3600)/60):2}'
    else:
        ManTime = "0:00"    

    return render_template('index.html',
                           maxA = gmaxAmpere,
                           minA = gminAmpere,
                           Power = gPower,
                           PowerOut = round(gPowerOut,1),
                           PowerIn = round(gPowerIn,1),
                           PowerProduced = round(gPowerProduced,1),
                           freePower = gFreePower,
                           freePowerSave = gFreePowerSave,
                           setPower = gSetPower,
                           current = gCurrent,
                           pause = gPause,
                           limit = round(gLimit/1000),
                           phase = gPhase,
                           timeout=30,
                           #actTime = time.strftime('%d.%m.%Y %H:%M:%S'),
                           actTime = time.strftime('%H:%M:%S'),
                           debug = gDebug,
                           manual = ManTime,
    )                   

@app.route('/set_manual')
def set_manual():

    global gManTime

    aTime = time.time()

    if gManTime > aTime:
        control = switchPhase(0)
        printdebug(0,f'set_manual off Control {control}')
        time.sleep(10)
        gManTime = 0
        
    else:
        control = switchPhase(gPower['P3']['max'])
        printdebug(0,f'set_manual on Control {control}')
        gManTime = time.time() + 86400

    waitFlag.set()

    return index()
    
@app.route('/set_debug')
def set_debug():

    global gDebug

    gDebug += 1
    if gDebug > 3:
        gDebug = 0

    waitFlag.set()

    return index()             

@app.route('/set_max_a')
def set_max_a():

    global gmaxAmpere
    setAmpere(max = float(request.args.get('vmax_a')), min = 6)

    waitFlag.set()

    return index()             

@app.route('/set_limit')
def set_limit():

    global gLimit

    gLimit = round(float(request.args.get('vlimit'))*1000)
    sendNRGkick(f'/control?energy_limit={ gLimit }')

    waitFlag.set()

    return index()             


if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=8001)
