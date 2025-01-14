# Ce script extrait les données du système Hikvision. Pour utiliser:
# 1) Dans Power BI, créer une nouvelle source de données de type "Python script" et copier/coller ce fichier en entier
#    Ceci dépend d'une installation Python sur l'ordinateur où on développe le rapport Power BI. S'assurer que l'exécutable de Python soit dans le PATH.
# 2) Pour permettre le rafraîchissement de ces données une fois le rapport dans le Power BI Service, qui ne supporte pas de lui-même exécuter un script Python,
#    installer le "On-Premises Data Gateway (Personal mode)" selon les instructions ici: https://learn.microsoft.com/en-ca/power-bi/connect-data/service-gateway-onprem.
# 3) Dans le Power BI Service, aller dans les paramètres du data set du rapport en question, et vérifier que la section "Gateway connection" indique l'utilisation
#    de ce qui vient d'être installé. En cas d'erreur de type "Module 'xyz' not found" (erreur d'exécution du script Python), simplement installer les modules manquants
#    sur le serveur hôte avec "pip install xyz".

# Extracts data from a Hikvision camera system equipped with license plate recognition
#
# Authentication is based on https://github.com/JakeVincet/nvt/blob/master/2018/hikvision/gb_hikvision_ip_camera_default_credentials.nasl

import datetime
import pandas as pd
import requests
import re
import time
import uuid
import xml.etree.ElementTree as ET
from hashlib import sha256
from urllib.parse import parse_qs, urlparse

# Target server and port
host = '91.183.96.120:8101'

# Auth params
username = '' # demander à Gilles
password = '' # demander à Gilles

# Search parameters
searchId = uuid.uuid4() # common id used across paging requests
searchQueryPageSize = 50
searchRangeDaysBack = 14

# Camera track identifiers
tracks = [103, 203]

def get_authentication_cookies():
    # Get encryption params
    capabilitiesUrl = f'http://{host}/ISAPI/Security/sessionLogin/capabilities?username={username}'
    response = requests.get(capabilitiesUrl)

    sessionId = re.search(
        '<sessionID>([a-zA-Z0-9]+)</sessionID>', response.text).group(1)
    challenge = re.search(
        '<challenge>([a-zA-Z0-9]+)</challenge>', response.text).group(1)
    iterations = re.search(
        '<iterations>([0-9]+)</iterations>', response.text).group(1)
    iterations = int(iterations)
    salt = re.search('<salt>([a-zA-Z0-9]+)</salt>', response.text).group(1)

    # Encrypt password
    encryptedPassword = sha256(
        (username + salt + password).encode('utf-8')).hexdigest()
    encryptedPassword = sha256(
        (encryptedPassword + challenge).encode('utf-8')).hexdigest()

    for i in range(2, iterations):
        encryptedPassword = sha256(
            encryptedPassword.encode('utf-8')).hexdigest()

    # Login
    body = f"<SessionLogin><userName>{username}</userName><password>{encryptedPassword}</password><sessionID>{sessionId}</sessionID></SessionLogin>"

    unixTime = int(time.time())
    sessionLoginUrl = f"http://{host}/ISAPI/Security/sessionLogin?timeStamp={unixTime}"

    sessionLoginResponse = requests.post(sessionLoginUrl, data=body)

    return sessionLoginResponse.cookies

def get_search_body(trackId, startTime, endTime, page):
    searchResultPosition = searchQueryPageSize * (page - 1)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
        <CMSearchDescription>
        <searchID>{searchId}</searchID>
        <trackList>
            <trackID>{trackId}</trackID>
        </trackList>
        <timeSpanList>
            <timeSpan>
                <startTime>{startTime}</startTime>
                <endTime>{endTime}</endTime>
            </timeSpan>
        </timeSpanList>
        <contentTypeList>
            <contentType>metadata</contentType>
        </contentTypeList>
        <maxResults>{searchQueryPageSize}</maxResults>
        <searchResultPostion>{searchResultPosition}</searchResultPostion>
        <metadataList>
            <metadataDescriptor>//recordType.meta.std-cgi.com/vehicleDetection</metadataDescriptor>
            <SearchProperity>
                <plateSearchMask />
                <country>255</country>
            </SearchProperity>
        </metadataList>
        </CMSearchDescription>"""


def get_results_for_track(track, cookies):
    searchUrl = f'http://{host}/ISAPI/ContentMgmt/search'
    hasMore = True
    page = 0
    startTime = datetime.date.today() + datetime.timedelta(days=-searchRangeDaysBack)
    endTime = datetime.date.today() + datetime.timedelta(days=1)
    startTime = "{:%Y-%m-%dT%H:%M:%S%Z}".format(startTime)
    endTime = "{:%Y-%m-%dT%H:%M:%S%Z}".format(endTime)
    data = []

    while (hasMore):
        page += 1
        searchBody = get_search_body(track, startTime, endTime, page)

        response = requests.post(searchUrl, data=searchBody,
                                 cookies=cookies)
        root = ET.fromstring(response.content)
        hasMore = root.find('{*}responseStatusStrg').text == 'MORE'

        for result in root.findall('./{*}matchList/{*}searchMatchItem'):
            timestamp = result.find('./{*}timeSpan/{*}startTime').text
            imageUrl = result.find(
                './{*}mediaSegmentDescriptor/{*}playbackURI').text
            parsed = urlparse(imageUrl)
            filename = parse_qs(parsed.query).get('name')[0]

            # filename looks like ch00002_00000003715078228105600525123_AB318QN
            # last part is license plate (can be 'unknown')
            licensePlate = filename.split('_')[-1]

            data.append([track, timestamp, licensePlate, imageUrl])

    return data

# Search
authenticationCookies = get_authentication_cookies()

data = []

for track in tracks:
    trackData = get_results_for_track(track, authenticationCookies)
    data.extend(trackData)

# Output
results = pd.DataFrame(
    data, columns=['Track', 'Timestamp', 'LicensePlate', 'ImageUrl'], dtype=None)
print(results)