#!/usr/bin/env python
# This file is part of Responder, a network take-over set of tools 
# created and maintained by Laurent Gaffie.
# email: laurent.gaffie@gmail.com
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import re,sys,socket,struct
import datetime
import multiprocessing
from socket import *
from odict import OrderedDict
import optparse
import binascii
from RunFingerPackets import *
from sys import exit

__version__ = "0.8"

parser = optparse.OptionParser(usage='python %prog -i 10.10.10.224\nor:\npython %prog -i 10.10.10.0/24', version=__version__, prog=sys.argv[0])

parser.add_option('-i','--ip', action="store", help="Target IP address or class C", dest="TARGET", metavar="10.10.10.224", default=None)
parser.add_option('-a','--all', action="store_true", help="Performs all checks (including MS17-010)", dest="all", default=False)
parser.add_option('-g','--grep', action="store_true", dest="grep_output", default=False, help="Output in grepable format")
options, args = parser.parse_args()

if options.TARGET is None:
    print("\n-i Mandatory option is missing, please provide a target or target range.\n")
    parser.print_help()
    exit(-1)

Timeout = 2
Host = options.TARGET
MS17010Check = options.all

class Packet():
    fields = OrderedDict([
    ])
    def __init__(self, **kw):
        self.fields = OrderedDict(self.__class__.fields)
        for k,v in kw.items():
            if callable(v):
                self.fields[k] = v(self.fields[k])
            else:
                self.fields[k] = v
    def __str__(self):
        return "".join(map(str, self.fields.values()))

def longueur(payload):
    length = struct.pack(">i", len(''.join(payload)))
    return length

def GetBootTime(data):
    Filetime = int(struct.unpack('<q',data)[0])
    t = divmod(Filetime - 116444736000000000, 10000000)
    time = datetime.datetime.fromtimestamp(t[0])
    return time, time.strftime('%Y-%m-%d %H:%M:%S')


#####################

def IsSigningEnabled(data): 
    if data[39] == "\x0f":
        return True
    else:
        return False

def atod(a): 
    return struct.unpack("!L",inet_aton(a))[0]

def dtoa(d): 
    return inet_ntoa(struct.pack("!L", d))

def OsNameClientVersion(data):
    try:
        length = struct.unpack('<H',data[43:45])[0]
        if length > 255:
            OsVersion, ClientVersion = tuple([e.replace('\x00','') for e in data[48+length:].split('\x00\x00\x00')[:2]])
            return OsVersion, ClientVersion
        if length <= 255:
            OsVersion, ClientVersion = tuple([e.replace('\x00','') for e in data[47+length:].split('\x00\x00\x00')[:2]])
            return OsVersion, ClientVersion
    except:
         return "Could not fingerprint Os version.", "Could not fingerprint LanManager Client version"
def GetHostnameAndDomainName(data):
    try:
        DomainJoined, Hostname = tuple([e.replace('\x00','') for e in data[81:].split('\x00\x00\x00')[:2]])
        Time = GetBootTime(data[60:68])
        #If max length domain name, there won't be a \x00\x00\x00 delineator to split on
        if Hostname == '':
            DomainJoined = data[81:110].replace('\x00','')
            Hostname = data[113:].replace('\x00','')
        return Hostname, DomainJoined, Time
    except:
         return "Could not get Hostname.", "Could not get Domain joined"

def DomainGrab(Host):
    s = socket(AF_INET, SOCK_STREAM)
    try:
       s.settimeout(Timeout)
       s.connect(Host)
    except:
       pass
    try:
       h = SMBHeaderLanMan(cmd="\x72",mid="\x01\x00",flag1="\x00", flag2="\x00\x00")
       n = SMBNegoDataLanMan()
       packet0 = str(h)+str(n)
       buffer0 = longueur(packet0)+packet0
       s.send(buffer0)
       data = s.recv(2048)
       s.close()
       if data[8:10] == "\x72\x00":
          return GetHostnameAndDomainName(data)
    except:
       pass 

def SmbFinger(Host):
    s = socket(AF_INET, SOCK_STREAM)
    try:
       s.settimeout(Timeout)
       s.connect(Host)
    except:
       pass
    try:     
       h = SMBHeader(cmd="\x72",flag1="\x18",flag2="\x53\xc8")
       n = SMBNego(Data = SMBNegoData())
       n.calculate()
       packet0 = str(h)+str(n)
       buffer0 = longueur(packet0)+packet0
       s.send(buffer0)
       data = s.recv(2048)
       signing = IsSigningEnabled(data)
       if data[8:10] == "\x72\x00":
          head = SMBHeader(cmd="\x73",flag1="\x18",flag2="\x17\xc8",uid="\x00\x00")
          t = SMBSessionFingerData()
          packet0 = str(head)+str(t)
          buffer1 = longueur(packet0)+packet0  
          s.send(buffer1) 
          data = s.recv(2048)
       if data[8:10] == "\x73\x16":
          OsVersion, ClientVersion = OsNameClientVersion(data)
          return signing, OsVersion, ClientVersion
    except:
       pass


def check_ms17_010(Host):
    
    negotiate_protocol_request = binascii.unhexlify(
        "00000054ff534d42720000000018012800000000000000000000000000002f4b0000c55e003100024c414e4d414e312e3000024c4d312e325830303200024e54204c414e4d414e20312e3000024e54204c4d20302e313200")
    session_setup_request = binascii.unhexlify(
        "00000063ff534d42730000000018012000000000000000000000000000002f4b0000c55e0dff000000dfff02000100000000000000000000000000400000002600002e0057696e646f7773203230303020323139350057696e646f7773203230303020352e3000")
    try:
        s = socket(AF_INET, SOCK_STREAM)
        s.settimeout(Timeout)
        s.connect(Host)
        s.send(negotiate_protocol_request)
        s.recv(1024)
        s.send(session_setup_request)
        data = s.recv(1024)
        user_id = data[32:34]
        tree_connect_andx_request = "000000%xff534d42750000000018012000000000000000000000000000002f4b%sc55e04ff000000000001001a00005c5c%s5c49504324003f3f3f3f3f00" % ((58 + len(Host[0])), user_id.encode('hex'), Host[0].encode('hex'))
        s.send(binascii.unhexlify(tree_connect_andx_request))
        data = s.recv(1024)
        allid = data[28:36]
        payload = "0000004aff534d422500000000180128000000000000000000000000%s1000000000ffffffff0000000000000000000000004a0000004a0002002300000007005c504950455c00" % allid.encode('hex')
        s.send(binascii.unhexlify(payload))
        data = s.recv(1024)
        s.close()
        if "\x05\x02\x00\xc0" in data:
            return True
        else:
            return False
        s.close()
    except Exception as e:
        print(e)
        return False


def check_smb_null_session(host):
    s = socket(AF_INET, SOCK_STREAM)
    try:
        s.settimeout(Timeout)
        s.connect(host)
        h = SMBHeader(cmd="\x72",flag1="\x18", flag2="\x53\xc8")
        n = SMBNego(Data = SMBNegoData())
        n.calculate()
        packet0 = str(h)+str(n)
        buffer0 = longueur(packet0)+packet0
        s.send(buffer0)
        data = s.recv(2048)
        if data[8:10] == "\x75\x00":
            return True
        else:
            return False
    except Exception:
        return False

##################
#run it
def ShowResults(Host):
    try:
       Hostname, DomainJoined, Time = DomainGrab(Host)
       Signing, OsVer, LanManClient = SmbFinger(Host)
       NullSess = check_smb_null_session(Host)
       if MS17010Check:
          Ms17010 = check_ms17_010(Host)
          print "Retrieving information for %s..."%Host[0]
          print "SMB signing:", Signing
          print "Null Sessions Allowed:", NullSess
          print "Vulnerable to MS17-010:", Ms17010
          print "Server Time:", Time[1]
          print "OS version: '%s'\nLanman Client: '%s'"%(OsVer, LanManClient)
          print "Machine Hostname: '%s'\nThis machine is part of the '%s' domain\n"%(Hostname, DomainJoined)
       else:
          print "Retrieving information for %s..."%Host[0]
          print "SMB signing:", Signing
          print "Null Sessions Allowed:", NullSess
          print "Server Time:", Time[1]
          print "OS version: '%s'\nLanman Client: '%s'"%(OsVer, LanManClient)
          print "Machine Hostname: '%s'\nThis machine is part of the '%s' domain\n"%(Hostname, DomainJoined)
    except:
       pass

def ShowSmallResults(Host):
    s = socket(AF_INET, SOCK_STREAM)
    try:
       s.settimeout(Timeout)
       s.connect(Host)
    except:
       return False

    try:
       if MS17010Check:
          Hostname, DomainJoined, Time = DomainGrab(Host)
          Signing, OsVer, LanManClient = SmbFinger(Host)
          NullSess = check_smb_null_session(Host)
          Ms17010 = check_ms17_010(Host)
          message_ms17010 = ", MS17-010: {}".format(Ms17010)
          print("['{}', Os:'{}', Domain:'{}', Signing:'{}', Time:'{}', Null Session: {} {}".format(Host[0], OsVer, DomainJoined, Signing, Time[1],NullSess, message_ms17010))
       else:
          Hostname, DomainJoined, Time = DomainGrab(Host)
          Signing, OsVer, LanManClient = SmbFinger(Host)
          NullSess = check_smb_null_session(Host)
          print("['{}', Os:'{}', Domain:'{}', Signing:'{}', Time:'{}', Null Session: {}".format(Host[0], OsVer, DomainJoined, Signing, Time[1],NullSess))
    except Exception as err:
        pass

def RunFinger(Host):
    m = re.search("/", str(Host))
    if m:
        net,_,mask = Host.partition('/')
        mask = int(mask)
        net = atod(net)
        threads = []
        if options.grep_output:
            func = ShowSmallResults
        else:
            func = ShowResults
        for host in (dtoa(net+n) for n in range(0, 1<<32-mask)):
            p = multiprocessing.Process(target=func, args=((host,445),))
            threads.append(p)
            p.start()
    else:
        if options.grep_output:
            ShowSmallResults((Host,445))
        else:
            ShowResults((Host,445))

RunFinger(Host)
