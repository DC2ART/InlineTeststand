"""
Date created: 			07.08.2015
Author: 				Arthur Bliedung
Company: 				HE-System Electronic
ModuleName: 			InlineClasses
Path: 					C:\Python34
Python version: 		Python 3.4
Content:				Definitions of Classes and initializations of global variables

"""
from labjack import ljm
from array import array
import ctypes
from enum import IntEnum
import sys
import time

#Number of DUTs per shuttle
NDUT = 9
#Number of test-data is to be stored to compare errors in order to assess repetitive errors such as broken needles
MEMCYC	= 3		
#------------------------------------------------Definition of Classes-----------------------------------------------------------------------------------------
#Order in which the qObj is handed from the InlineTester to the InlineGUI
class QGUI(IntEnum):
	Gate = 0
	Phase = 1
	Source = 2
	Dutstatus = 3
	Dutstati_Old = 4
	TesterState = 5
	Ntot = 6
	Npass = 7
	Nfail = 8
	Ngs_short = 9
	Nnot_bonded = 10
	Nds_short = 11
	State = 12
	Mode = 13

class MODE(IntEnum):
	# 	something like this is not possible from the outside: 
	#	MODE.DEBUG = 7
	DEBUG = 0
	SERVICE = 1
	PRODUCTION = 2
	#Mode is used for following decisions:
	#PROG_MODE = MODE.PRODUCTION	#Can be in Production or Service mode
									#Production: normal test flow
									#Service: no test flow, tester is controlled by service staff
	#OUTPUT_MODE = MODE.PRODUCTION	#Production: reduced information output	
									#Debug: Verbose Output
									#Setting is controlled by user and implemented in debug_output


class LIMIT(IntEnum):
	MAX_PHASE = 0
	NOM_PHASE = 1
	MIN_PHASE = 2
	MAX_GATE = 3
	NOM_GATE = 4
	MIN_GATE = 5
	MAX_SOURCE = 6
	NOM_SOURCE = 7
	MIN_SOURCE = 8
	VOFF = 9


class ERR(IntEnum):
	PASSED = 0
	VLOW = 1
	VHIGH = 2
	TESTER_FAULT = 3
	NOT_BONDED = 4
	GS_SHORT = 5
	DS_SHORT = 6
	UNKNOWN = 7
	NORES = 8

"""
digital IO configuration:
FIO0-FIO7 = DIO0-DIO7
EIO0-EIO7 = DIO8-DIO15
CIO0-CIO3 = DIO16-DIO19
MIO0-MIO2 = DIO20-DIO22
"""

#Define Actors and Sensor Ports
class Ports(IntEnum):
	"""#example for using the class Ports
	#int_myport = Ports.SHUTTLE_VALVE
	#str_myport = str(int(Ports.SHUTTLE_VALVE))
	#print("intport %d, stringport %s" % (int_myport, "DIO"+str_myport) )"""
	#Define Actors and Sensor Ports
	DOUT_3V3ISO_ON = 0				#FIO0
	DOUT_VPHASE_REV_OFF = 1			#FIO1
	DOUT_VPHASE_ON = 2				#FIO2
	DOUT_VGATE_ON = 3				#FIO3
	BRDAVLBL_SMEMA_DIN = 4			#FIO4
	BRDAVLBL_SMEMA_DOUT = 5			#FIO5
	SCL_IN = 6						#FIO6
	SDA_IN = 7						#FIO7
	SHUTTLE_VALVE = 8				#EIO0
	STOPPER_VALVE = 9				#EIO1
	SHUTTLE_VALVE_UPPER_POS = 10	#EIO2
	SHUTTLE_VALVE_LOWER_POS = 11	#EIO3
	BAND_MOTOR = 12					#EIO4
	SHUTTLE_AVLBL = 13				#EIO5
	RDY2RCV_SMEMA_DIN = 14			#EIO6
	RDY2RCV_SMEMA_DOUT = 15			#EIO7
	
#Define Actors and Sensor Ports

#Define Process_State
class STATE(IntEnum):
	ENTRY = 0			#State machine entry point / 
						#User Logon: decision which mode is executed: Production or Service 
						#Start of GUI for Production of Service Mode
	INIT = 1			#Initialize all variables of states, names and results
						#Note that Init and Entry are not the same:
						#In contrast to Entry, Init can be reentered e.g. from Service Mode, Entry level
	LOGON = 2			#User logs in with user name and passwort
	IDLE = 3			#Waiting until Shuttle is available
	RDY4TST = 4			#Ready for Testing: Shuttle was recognized by inductive sensor, 
						#Shuttle is in upper position, 
						#Needle are contacted correctly
	TESTING = 5			#Test is in progress
	EVALUATE = 6		#Compare the acquired voltages with the defined limits
	GETSN = 7			#Get a serial number of a DUT in the shuttle
	GETLOT = 8
	SERVICE = 9			#Test waits for input of service personell, labjack modules are opened
	HALT = 10			#Operator Input: Halt testing: current test is finished, 
						#the shuttle is moved down
						#The tester variables are not deleted e.g. statistic data, user name
	ERROR = 11			#Tester Error is set if the same error occurs at the same shuttle position for MEMCYC times
	EXIT = 12			#No further shuttles are tested, 
						#tester and PC can be shutdown
						#Notify operator to shutdown powersupply
	"""#Example for using the class Process_State
	#print("the state is %d" % (Process_State.Test_Error + 1))"""
	#Define Process_State


#class for flags and test results
class STATUS(IntEnum):
	FAILED = 0
	ERROR = 1
	PASSED = 2
	NORES = 3
	

#Define states for relays and valves
class states(IntEnum):
	SET = 1		#e.g. SHUTTLE_VALVE_LOWER_POS = 0 (Optocoupler output is in logical state "LOW") -> SHUTTLE_VALVE is in lower position i.e. SHUTTLE_VALVE_LOWER_POS = states.SET 
	CLEAR = 0	#e.g. a relay DOUT_VGATE_ON has not been activated then it is clear. The expression (DOUT_VGATE_ON == states.CLEAR) would be true
class position(IntEnum):
	UP = 1
	DOWN = 0
#Define states for relays and valves