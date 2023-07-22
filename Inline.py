"""
Date created: 			27.04.2015
Author: 				Arthur Bliedung
Company: 				HE-System Electronic
Filename: 				Inline.py
Path: 					C:\Python34
Python version: 		Python 3.4
Content:				Test Program

Inline Function Test with Labjack T7 via USB
Project: 1447, SSSPR
Purpose: Identify gate-source / drain-source / drain-gate short circuits after the bond process prior to the optical inspection
Function: Inline Test of 9 SSSPRs in a shuttle 
	1. switch on phase voltage reversed (as needle test, the SSSPR-MOSFETs are used as intrinsic diodes), Id = 10mA
	2. switch on phase voltage in correct direction, measure current (in case of a drain-source short current would flow without gate-source voltage)
	3. switch on and measure gate-voltage, measure drain-current 
	4. switch off gate-source voltage and measure drain-current again

Additional functions: 
	1. communication via SMEMA interface
	2. display of yield rate in order to enable fast reaction time in case of increased amounts of gate-source short circuits
	3. Control movement of needle adapter

required proprietary modules:
	1. C:\Python34\InlineClasses.py
	2. C:\Python34\InlineFuncs.py


Python-Setup:
	Labjack drivers:
	C:\Python34\Lib\labjack\ljm

basic functions and examples:
	C:\Python34\Lib\Python_LJM\Examples

program start cmd
	type: C:\Python34\python C:\Python34\Inline.py
	or
	python C:\Python34\Inline.py (after python was added as environment variable: Windows -> Computer -> Eigenschaften -> Einstellungen ändern -> Erweitert -> Umgebungsvariablen)
"""

from labjack import ljm
from array import array
import ctypes
from enum import IntEnum
import sys
import time
from datetime import date
import threading
import queue
from InlineClasses import MODE, LIMIT, Ports, states, position, STATE, STATUS, ERR, QGUI, NDUT, MEMCYC
from InlineGUI import ShuttleGUI
import tkinter
import random



#------------------------------------------------------------------------Inline Tester State Machine-----------------------------------------------------------------------
class InlineStateMachine:
	def __init__(self, master):
		self.AN_CH = 14						#Number of analog channels
		self.DIO_CH = 23					#Number of digital channels per 
		self.NLJM = 2						#Number of LabjackModules
		
		#Flags as basis to set the state in which the tester state machine is in
		self.PROG_MODE = MODE.PRODUCTION	#Program Mode PRODUCTION: normal test flow, SERVICE: Service staff can control actor / sensors / test flow
		self.OUTPUT_MODE = MODE.PRODUCTION	#Output Mode DEBUG: Verbose Output in cmd window for debugging purposes PRODUCTION: no output
		self.ACCESS_LEVEL = MODE.PRODUCTION	#Access Level of user, is used to define PROG_MODE SERVICE and PRODUCTION 
		self.USERNAME = "NONAMEENTERED"		
		self.LOGON_OK = STATUS.FAILED		
		self.REQ_SN = states.CLEAR				#REQ_SN = states.CLEAR: No SerialNo (from Scanner) is acquired
		self.REQ_LOTN = states.CLEAR			#REQ_SN = states.CLEAR: No LotNo is required
		self.SERIAL	= "0"					#The Serial number of any DUT in the current shuttle which is to be tested
		self.LOTCODE = "0"					#The Current Lot Code

		self.TIME_TESTSTART = time.localtime()	#Array with 6 fields: Year, Month, Day, ...
												#TIME_TESTSTART: Used for logging testdata
		self.TIME_RUNSTART = float(0)			#Absolute time in seconds since epoch 01.01.1970
		self.TIME_RUNDSTOP = float(0)			#Times are used to calculate Test Time with 1 sec precision(without having to work around 1h / 1min / 24h etc. cycles)

		self.TESTER_STATUS = STATUS.NORES		#Status of the whole test system, can be NORES, ERROR, PASSED		
		self.TESTSTEP = "default"				#Name of a test step for the protocol

		self.DUTSTATUS = list(range(0, NDUT))		#Status of complete test of each DUT (Device under Test, SSSPR Module in the shuttle)
		self.DUTSTATUSTMP = list(range(0, NDUT))	#For Evaluation of each test step
		self.DUTSTATUSMEM = list(range(0, NDUT*MEMCYC))	#DUT Results from last shuttle
	
		for i in range(0, NDUT):
			self.DUTSTATUS[i] = ERR.NORES
			self.DUTSTATUSTMP[i] = ERR.NORES
		
		for m in range(0, MEMCYC):
			for i in range(0, NDUT):	
				self.DUTSTATUSMEM[m*NDUT + i] = ERR.NORES
				#quasi 2-D Array
				#DUTSTATMEM[0...8] 		contains DUT Error Codes from last shuttle (= N-1)
				#= DUTSTATMEM[m=0, i=0...8]
				#DUTSTATMEM[9...17] 	contains DUT Error Codes from shuttle N-2
				#= DUTSTATMEM[m=1, i=0...8]
				...
	
		self.TotalDUTsTested = 0		
		self.TotalDUTsPassed = 0
		self.TotalDUTsFailed = 0
		self.TotalDUTsGSShort = 0
		self.TotalDUTsNotBonded = 0
		self.TotalDUTsDSShort = 0

		self.SN_LJM1 = "470011540"				#change only if labjack modules are changed
		self.SN_LJM2 = "470011571"				#change only if labjack modules are changed
		self.handle1 = 0						#Handle (int value) for identification of the Labjack Module
		self.handle2 = 0						#Handle (int value) for identification of the Labjack Module
		self.error = 0							#error as return value for methods
		self.LabjacksOpened = states.CLEAR		#if LabjacksOpened = CLEAR -> all modules are closed / if set all modules are opened
												#this flag enables closing / opening modules only if they were opened / closed

		"""
		--------------------------Voltage divider factors according to AN_inputs from 0 ... AN_CH----------------------------
			Ermittlung der Faktoren: 
		
			1. Teilungsfaktor für den Kanal, dessen Teilungsfaktor festgestellt werden soll ("Kanal") zunächst auf 1.0 setzen
			2. Messen der vollen Spannung und der geteilten Spannung mit kalibriertem Spannungs-Messgerät, das eine ausreichend hohe Spannungsgenauigkeit hat (ca. 10mV auf 10V also 0.1% FS)
			3. nun kann der tatsächliche Teilungsfaktor berechnet werden (volle Spannung / geteilte Spannung)
			4. zusätzlich kann noch die Präzision der Messung aus dem analogen Eingang des Labjack mit der Messung aus dem kalibrierten Spannungsmessgerät verglichen werden
			Kommentar zu Inbetriebnahme AIN_GATEMO9: hier wird ein deutlich niedrigerer Spannungswert für VGATE gemessen -> Kalibrierungsfaktor ist höher (2.8184 statt wie für die anderen Berechnet 2.6027)
			Die Spannung ist tatsächlich niedriger und wird nicht etwa von dem ADWandler falsch dargestellt
			Die Genauigkeit der AD-Wandlung ist bei AIN0..8 (AIN_GATEMO1..9) gleich und in Ordnung, dies wurde mit dem agilent 34401A und 3.3V unabhängig von der Gate-Spannung gemessen (16.06.2015)
		"""

		self.DIV_GATE = array("f", [2.6027, 2.6027, 2.6027, 2.6027, 2.6027, 2.6027, 2.6027, 2.6027, 2.6027])		#AINmeasured(in V)*DIV_GATE = DUT_GATE_Voltage(in V)
		self.DIV_PHASE = array("f", [3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0])									#AINmeasured(in V)*DIV_PHASE = DUT_PHASE_Voltage (in V)
		self.DIV_SOURCE = array("f", [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0])						#AINmeasured*DIV_SOURCE = DUT_Drain_Current in mA
		
		#Set the initial Tester States for the state machine
		#By storing the previous state repetition errors counters / reinit-steps etc. can be set
		self.Prev_State = STATE.ENTRY
		self.This_State = STATE.ENTRY
		self.Next_State = STATE.ENTRY

		self.master = master
		self.QMAXSIZE = 20
		self.guiqueue = queue.Queue(maxsize = self.QMAXSIZE)
	
		self.VPhaseDUT = list(range(0, NDUT))
		self.VGateDUT = list(range(0, NDUT))
		self.VSourceDUT = list(range(0, NDUT))
		self.EvalDUTRes = list(range(0, NDUT))
		self.ErrorList =  list(range(0, NDUT))
		
		for i in range(0, NDUT):
			self.VGateDUT[i] = float(0.00-0.1*i)
			self.VPhaseDUT[i] = float(0.00-0.2*i)
			self.VSourceDUT[i] = float(0.00-0.3*i)
			self.EvalDUTRes[i] = STATUS.FAILED
			self.ErrorList[i] = ERR.VLOW
			
		#Limit definition
		self.InlineLimits = list(range(0, len(LIMIT)))
		self.InlineLimits[LIMIT.MAX_GATE] = 17.0
		self.InlineLimits[LIMIT.NOM_GATE] = 15.0
		self.InlineLimits[LIMIT.MIN_GATE] = 13.0
		self.InlineLimits[LIMIT.MAX_PHASE] = 26.0
		self.InlineLimits[LIMIT.NOM_PHASE] = 24.0
		self.InlineLimits[LIMIT.MIN_PHASE] = 22.0
		self.InlineLimits[LIMIT.MAX_SOURCE] = 1.5
		self.InlineLimits[LIMIT.NOM_SOURCE] = 1.0
		self.InlineLimits[LIMIT.MIN_SOURCE] = 0.8
		self.InlineLimits[LIMIT.VOFF] = 0.08		#+/-LIMIT.VOFF: range for Voltages which are supposed to be switched off 

		#Set up the Queue from which the GUI takes the information
		self.qObj = list(range(0, 14))	#length QGUI
		self.qObj[QGUI.Gate] = self.VGateDUT
		self.qObj[QGUI.Phase] = self.VPhaseDUT
		self.qObj[QGUI.Source] = self.VSourceDUT
		self.qObj[QGUI.Dutstatus] = self.DUTSTATUS
		self.qObj[QGUI.Dutstati_Old] = self.DUTSTATUSMEM
		self.qObj[QGUI.TesterState] = self.TESTER_STATUS
		self.qObj[QGUI.Ntot] = self.TotalDUTsTested
		self.qObj[QGUI.Npass] = self.TotalDUTsPassed
		self.qObj[QGUI.Nfail] = self.TotalDUTsFailed
		self.qObj[QGUI.Ngs_short] = self.TotalDUTsGSShort
		self.qObj[QGUI.Nnot_bonded] = self.TotalDUTsNotBonded
		self.qObj[QGUI.Nds_short] = self.TotalDUTsDSShort		
		self.qObj[QGUI.State] = self.Next_State
		self.qObj[QGUI.Mode] = self.PROG_MODE

		self.guiqueue.put(self.qObj)
	
		#self.gui = ShuttleGUI(self.master, self.guiqueue, self.startCommand, self.haltCommand, self.exitCommand, self.gui_shuttlevalve_up, self.gui_shuttlevalve_down, self.gui_vphase_on, self.gui_vphase_off, self.gui_vphase_rev_off, self.gui_vphase_rev_on, self.gui_gate_on, self.gui_vgate_off, self.GetVGate, self.GetVPhase, self.GetVSource)

		#UserStart is set / reset by the gui via the functions startCommand / haltCommand to indicate start stop
		self.UserStart = 0
		self.UserExit = 0
		
		#start the inline tester state machine which runs in parallel to the inlineGui
		self.thread1 = threading.Thread(target=self.state_machine)
		self.thread1.start()
	#------------------------------END CONSTRUCTOR InlineStateMachine

	#evaluate the command line inputs
	#command line arguments are described in the print statement of the help section -h
	def eval_cmdargs(self):
		#reference to the fields of the returned list
		for i in range(len(sys.argv)):
			#Program Mode
			if sys.argv[i] == "-m":
				if sys.argv[i+1] == "SERVICE":
					self.PROG_MODE = MODE.SERVICE
				else:
					self.PROG_MODE = MODE.PRODUCTION
			#Output Mode
			if sys.argv[i] == "-v":
				self.OUTPUT_MODE = MODE.DEBUG
				#else: init value of self.OUTPUT_MODE
			#User
			if sys.argv[i] == "-l":
				self.USERNAME = sys.argv[i+1]
				import getpass
				pswd = getpass.getpass('Password:')
				self.check_login(pswd)	#check login alters self.LOGON_OK, self.ACCESS_LEVEL
			#Omit password
			if sys.argv[i] == "-nl":
				self.LOGON_OK = STATUS.PASSED
			#Serial Number enabled?
			if sys.argv[i] == "-s":
				self.REQ_SN = states.SET
				print('Serial Number required')
			#Lot Code?
			if sys.argv[i] == "-LT":
				self.REQ_LOTN = states.SET
			if sys.argv[i] == "start":
				if sys.argv[i+1] == "Y":
					self.startCommand()
				else:
					self.haltCommand()
			if sys.argv[i] == "-h":
				print(	"-h print this help\n" 
						"\n"
						"-v enable verbose output\n"
						"-m [mode] \n" 
						"	mode can be:\n" 
						"	SERVICE:	test process is halted, only inputs of service personnel are executed\n\t\t access to tester functions and limit definition\n" 
						"	PRODUCTION:	normal mode\n" 
						"\n"
						"-l [user-name] \n" 
						"logon with username and password\n"
						"-s [mode] \n"
						"	serial numbers are scanned during testing / DMC Scanner installed"
						"	mode can be:\n" 
						"	N: No scanner installed\n"
						"	Y: Scanner installed\n"
						"-LT\n"
#						"lotcode = 0 no lotcode required, default logging path\n"
#						"lotcode = 1 ... 999999: logging in lotcode path\n"
						"-start [mode]"
						"	mode can be:\n" 
						"	start immediately after hitting return"
						"	N: No, start from GUI\n"
						"	Y: Yes, start immediately\n"
						)

	def debug_output(self, str_in):
		#print debug strings in various functions if output-mode "DEBUG" is enabled, otherwise do noth'n
		if self.OUTPUT_MODE == MODE.DEBUG:
			print(str_in)	#if the output mode is Debug do verbose outputs
	#else:
		#do nothing
						
	def check_login(self, pwd):
		"""checks user login data
		the user data is in path
		each user has a separate file whose name (without extension) matches exactly the username 
		the user pwd is in the first line of the file
		the access level is in the second line 
		
		the function alters self.LOGON_OK, self.ACCESS_LEVEL
		"""
		#root path with user files
		path = "C:\Python34\\"
		ret_val = 1
		try:
			file = open( path + self.USERNAME + ".txt", "r")	#UserName has already been set by eval_cmdargs
			realpwd = file.readline()							#read first line with pwd
			accesslevel = file.readline()					#read second line with access level
		except IOError:
			self.debug_output("no such user")
			ret_val = 0
			raise
		except FileNotFoundError:
			self.debug_output("FileNotFoundError: no such user")
			ret_val = 0
			raise
		
		if ret_val == 1:			#user exists because file could be opened
			if (realpwd == pwd+"\n"):
				#print("check_login: logon successful\n")
				self.LOGON_OK = STATUS.PASSED
				self.debug_output("check_login: login succeeded")
				if accesslevel == "S":
					self.ACCESS_LEVEL = MODE.SERVICE
				else:
					self.ACCESS_LEVEL = MODE.PRODUCTION
			else:
				self.LOGON_OK = STATUS.FAILED
				self.debug_output("check_login: resetting the LOGON_STATUS to FAILED")
	
	#Open Labjack modules, initially two modules are assumed. Input: Module number, Output: handle ID
	def OpenLabjack(self, module):
		if module == 1:
			self.handle1 = ljm.openS("T7", "USB", self.SN_LJM1)
			info = ljm.getHandleInfo(self.handle1)
			self.debug_output("\nOpened LabJack Module 1 \n	Serial number: %i \n	value handle1 is: %i\n \n" % (info[2], self.handle1))
			ret_val = self.handle1
		elif module == 2:
			self.handle2 = ljm.openS("T7", "USB", self.SN_LJM2)
			info = ljm.getHandleInfo(self.handle2)
			ret_val = self.handle2
			self.debug_output("\nOpened LabJack Module 2 \n	Serial number: %i \n	value handle2 is: %i\n \n" % (info[2], self.handle2))
		else:
			print("OpenLabjack: wrong argument, Labjack Module %i not available" % module)
			ret_val = -1
		return ret_val

	#Close a labjack Module / Input: Handle / Output: Error, @ Successful closure error = None
	def CloseLabjack(self, module):
		if module == 1:
			# Close handle1
			error = ljm.close(self.handle1)
			self.debug_output("Closed Labjack Module %i, errors: %s " % (module, error))
		elif module == 2:
			# Close handle1
			error = ljm.close(self.handle2)
			self.debug_output("Closed Labjack Module %i, errors: %s " % (module, error))
		else:
			self.debug_output("CloseLabjack: wrong argument, Labjack Module not available" % module)
			error = -1
		return error	


	def SetRelay(self, dioport, state):
		"""Setting the dioport to state
			in case of failure the TESTER_STATUS is set to ERROR
			the outmode switch enables or disables verbose output
			for clarity dioport should be from the Ports-Enum Class, but any other port-number can also be handed
		
			handle is always handle1 since all the actors / sensors are connected to Labjack-Module 1
			if this should change in future hardware versions, the handle has to be determined by switch cases according to the incoming port
		
			In case of an error the function's return value is -1
			but the calling function won't have to check for this return value, since also the TESTER_STATUS is changed
		"""
		func_name = "SetRelay"
		ret_val = ljm.eWriteName(self.handle1, "DIO"+str(int(dioport)), state)
		if dioport == Ports.SHUTTLE_VALVE:
			shuttlevalvesetcounter = 0
			SHUTTLE_TICK = 0.05		#period in sec
			SHUTTLEMAXWAIT = 50		#period * ticks until TESTER_STATUS is set to ERROR

			if state == position.UP:
				target_pos = position.UP
				target_sens = Ports.SHUTTLE_VALVE_UPPER_POS
				oppos_pos = position.DOWN
				oppos_sens = Ports.SHUTTLE_VALVE_LOWER_POS
			elif state == position.DOWN:
				target_pos = position.DOWN
				target_sens = Ports.SHUTTLE_VALVE_LOWER_POS
				oppos_pos = position.UP
				oppos_sens =  Ports.SHUTTLE_VALVE_UPPER_POS
			else:
				self.debug_output("no such target position as %i", state)
	
			#Get Position and set timer
			while self.GetRelay(target_sens) != states.CLEAR and shuttlevalvesetcounter <= SHUTTLEMAXWAIT:
					time.sleep(SHUTTLE_TICK)
					shuttlevalvesetcounter += 1
					self.debug_output("Shuttle is moving, counter is %i" %shuttlevalvesetcounter)
					#Only for manual mode, NOT automatic mode: Switches have to be pressed during driving up
					if (state == position.UP) and (self.GetRelay(Ports.SHUTTLE_AVLBL) != states.CLEAR):
						self.TESTER_STATUS = STATUS.ERROR
						self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)
			#self.debug_output("waiting for shuttle to reach upper position, counter is %i" % shuttlevalvesetcounter)
			if shuttlevalvesetcounter >= SHUTTLEMAXWAIT:
				self.TESTER_STATUS = STATUS.ERROR
				self.schedule(STATE.HALT) #inform scheduler, so he can query the TESTER_STATUS flag and update the TESTER_STATUS in the gui


		if ret_val == None:
			self.debug_output("%s: %s was set to %s, Tester Status is %s" % (func_name, repr(dioport), repr(state), repr(self.TESTER_STATUS)))
		else:
			self.TESTER_STATUS = STATUS.ERROR
			self.schedule(STATE.HALT) #schedule queries the TESTER_STATUS flag
			ret_val = -1
			self.debug_output("Error %s: %s could not be set to %s" % (func_name, repr(dioport), repr(state)))
		return ret_val
	
	def GetRelay(self, dioport):
		"""Getting the state of dioport
		the other descriptions apply from the function SetRelay
		"""
		func_name = "GetRelay"
		ret_val = ljm.eReadName(self.handle1, "DIO"+str(int(dioport)))
		if ret_val == 0 or ret_val == 1:
			self.debug_output("%s: %s is %s" % (func_name, repr(dioport), repr(ret_val)))
		else:
			self.TESTER_STATUS = STATUS.ERROR
			ret_val = -1
			self.debug_output("Error %s: %s could not be set to %s" % (func_name, repr(dioport), repr(state)))
		return ret_val	
	
	
	#Acquire Gate-Voltages of all DUTs,  overview of analog channel assignment: C:\Python34\Analog_Channel_Assignment.txt
	#Write the new voltages to the GUIQueue
	def GetVGate(self):
		for i in range(0, NDUT):
			self.VGateDUT[i] = ljm.eReadName(self.handle1, "AIN"+str(i))
			#self.debug_output("GetVGate: VGate%i is %f V" % (i+1, self.VGateDUT[i]))
		#Write newly acquired voltages to the queue
		self.qObj[QGUI.Gate] = self.VGateDUT
		if self.guiqueue.qsize() < self.QMAXSIZE:
			self.guiqueue.put(self.qObj)

	#Acquire Phase-Voltages of all DUTs,  overview of analog channel assignment: C:\Python34\Analog_Channel_Assignment.txt
	#Write the new voltages to the GUIQueue
	def GetVPhase(self):
		#VPhase in first Labjack Module
		for i in range(0, 5):
			self.VPhaseDUT[i] = ljm.eReadName(self.handle1, "AIN"+str(i+9))
			#self.debug_output("GetVPhase: VPhase%i ( AIN%i of module %i) is %f V" % (i+1, i+9, 1, self.VPhaseDUT[i]))
		#VPhase in second Labjack Module
		for i in range(0, 4):
			self.VPhaseDUT[i+5] = ljm.eReadName(self.handle2, "AIN"+str(i))
			self.debug_output("GetVPhase: VPhase%i ( AIN%i of module %i) is %f V" % (i+6, i, 2, self.VPhaseDUT[i+5]))
		"""#Channel Assignment for VPhase:
		
			#Module1
			#AIN[9] 	= 	"AIN_PHASEMO1"
			#AIN[10] 	= 	"AIN_PHASEMO2"
			#AIN[11] 	= 	"AIN_PHASEMO3"
			#AIN[12] 	= 	"AIN_PHASEMO4"
			#AIN[13] 	=	"AIN_PHASEMO5"
			#Module2
			#AIN[0]	 	=	'AIN_PHASEMO6'
			#AIN[1] 	=	'AIN_PHASEMO7'
			#AIN[2] 	=	'AIN_PHASEMO8'
			#AIN[3]		=	'AIN_PHASEMO9'
			"""
		#Write newly acquired voltages to the queue
		self.qObj[QGUI.Phase] = self.VPhaseDUT
		if self.guiqueue.qsize() < self.QMAXSIZE:
			self.guiqueue.put(self.qObj)


 	#Acquire Analog channels of a Labjack Module
	#Write the new voltages to the GUIQueue
	def GetVSource(self):
		for i in range(0, NDUT):
			self.VSourceDUT[i] = ljm.eReadName(self.handle2, "AIN"+str(i+4))
			#self.debug_output("GetVPhase: VSource%i ( AIN%i of module %i) is %f V" % (i+1, i+4, 2, self.VSourceDUT[i]))

		#Write newly acquired voltages to the queue
		self.qObj[QGUI.Source] = self.VSourceDUT
		if self.guiqueue.qsize() < self.QMAXSIZE:
			self.guiqueue.put(self.qObj)
	

	def evaluate(self, showstr, listin, lowLimit, erronlow, upLimit, erronhigh, queueindex):
		"""
		the string with drawing text, prior to this the test step in self.TESTSTEP is shown
		evaluate gets as input the listin which is to be evaluated, 
		the lower / upper limits for the comparison, 
		the errornumbers in case the lower, upper limits are violated
		the index of the queue object which is to be put on the queue
		"""
		for i in range(0, len(listin)):
			if listin[i] < lowLimit:
				if erronlow != ERR.TESTER_FAULT:
					self.DUTSTATUSTMP[i] = erronlow 	#write result to DUTSTATUSTMP unless the error is significant and TESTER_STATUS is affected
				elif erronlow == ERR.TESTER_FAULT:
					self.TESTER_STATUS = STATUS.ERROR
					self.debug_output("TESTER_STATUS was set to STATUS.ERROR")
				else:
					self.TESTER_STATUS = STATUS.ERROR
			elif  listin[i] > upLimit:
				if erronlow != ERR.TESTER_FAULT:
					self.DUTSTATUSTMP[i] = erronhigh 	#write result to DUTSTATUS unless the error is significant and TESTER_STATUS is affected
				elif erronlow == ERR.TESTER_FAULT:
					self.TESTER_STATUS = STATUS.ERROR
					self.debug_output("TESTER_STATUS was set to STATUS.ERROR")
				else:
					self.TESTER_STATUS = STATUS.ERROR
			else:
				#DUT is passed
				#write result to DUTSTATUSTMP
				self.DUTSTATUSTMP[i] = ERR.PASSED
			

			self.debug_output("%s Mo%i: %2.3f V [%2.3f V ... %2.3f V] ErrCode: %i" % (self.TESTSTEP + showstr, i+1, listin[i], lowLimit, upLimit, self.DUTSTATUSTMP[i]))
			#put statistics to LoggingFile if verbose mode is enabled (self.OUTPUT_MODE = MODE.DEBUG)
			if self.OUTPUT_MODE == MODE.DEBUG:
				self.LoggingFile.write("%s Mo%i: %2.3f V [%2.3f V ... %2.3f V] ErrCode: %i\n" % (self.TESTSTEP + showstr, i+1, listin[i], lowLimit, upLimit, self.DUTSTATUSTMP[i]))
			
		#Update Status Colours in GUI for each test step only in Service Mode
		if self.PROG_MODE == MODE.SERVICE:		
			self.qObj[queueindex] = listin	#Voltage values
			self.qObj[QGUI.Dutstatus] = self.DUTSTATUSTMP	#Index with the errorcodes
		
			if self.guiqueue.qsize() < self.QMAXSIZE:
				self.guiqueue.put(self.qObj)
		 
	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope	
	def startCommand(self):
		self.UserStart = 1
		self.debug_output("Inline startCommand: activated self.UserStart is %i" % self.UserStart)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope
	def haltCommand(self):
		self.UserStart = 0
		self.debug_output("Inline haltCommand: activated self.UserStart is %i" % self.UserStart)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope
	def exitCommand(self):
		self.UserExit = 1
		self.debug_output("Inline exitCommand: activated ")

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope
	def gui_shuttlevalve_up(self):
		func_name = "gui_shuttlevalve_up"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.SHUTTLE_VALVE, position.UP)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_shuttlevalve_down(self):
		func_name = "gui_shuttlevalve_down"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)
			
	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_vphase_on(self):
		func_name = "gui_vphase_on"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VPHASE_ON, states.SET)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_vphase_off(self):
		func_name = "gui_vphase_off"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)

	
	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_vphase_rev_off(self):
		func_name = "gui_vphase_rev_off"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.SET)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_vphase_rev_on(self):
		func_name = "gui_vphase_rev_on"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)
			

			
			
	def gui_gate_on(self):
		func_name = "gui_vgate_on"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VGATE_ON, states.SET)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)

	#button function for the GUI
	#has to be without input parameters, therefore SetRelay is out of scope			
	def gui_vgate_off(self):
		func_name = "gui_vgate_off"
		if self.PROG_MODE == MODE.SERVICE:
			self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)
		else:
			self.debug_output("%s: Service Mode is not activated" % func_name)			
			
			
			

	def periodicCall(self):
		"""
		Check if there is something new in the queue.
		"""
		self.gui.processIncoming()
		if not self.UserStart:
			#even if the self.UserStart flag is cleared
			#the GUI will be forced to update the data
			#but the statemachine won't write data to queue in case UserStart is cleared
			#this enables to start / stop the testing process without having to terminate the process completely
			#time.sleep(0.5)
			self.master.after(502, self.periodicCall)
			#sys.exit(1)
		else:
			self.master.after(502, self.periodicCall)
			
	def schedule(self, nextState):
		self.qObj[QGUI.TesterState] = self.TESTER_STATUS
		self.qObj[QGUI.State] = self.Next_State
		self.qObj[QGUI.Mode] = self.PROG_MODE
		if self.guiqueue.qsize() < self.QMAXSIZE:
			self.guiqueue.put(self.qObj)
		"""
			Update the states and check status flags
		"""
		if self.UserExit == 0 and self.UserStart == 1:
			self.Prev_State = self.This_State
			self.This_State = self.Next_State
			self.Next_State = nextState
		if self.UserExit == 1:
			self.Next_State = STATE.EXIT
		if self.TESTER_STATUS == STATUS.ERROR:
			self.haltCommand()	#Stop testing, as if user halted the test, UserStart is set to zero, so that user can fix the problem and restart the test
			self.TESTER_STATUS = STATUS.NORES	#TESTER_STATUS is reset to NORES, so that after restarting, and going to init, the TEST_STATUS is re-evaluated
			self.Next_State = STATE.HALT
		if self.UserExit == 0  and self.UserStart == 0:
			if self.Prev_State == STATE.ENTRY or self.This_State == STATE.ENTRY:
				self.Prev_State = self.This_State
				self.This_State = self.Next_State
				self.Next_State = nextState				
			else:
				self.Prev_State = self.This_State
				self.This_State = self.Next_State
				self.Next_State = STATE.HALT
		#control output
		self.debug_output("schedule: self.UserExit is %i self.UserStart is %i TESTER_STATUS is %s" % (self.UserExit, self.UserStart, repr(self.TESTER_STATUS)))
		self.debug_output("schedule: Prev_State: %s,\nThis_State: %s,\nNext_State: %s\n" % (repr(self.Prev_State), repr(self.This_State), repr(self.Next_State)))
	
	
	
	def selftest(self):
		#Init: Shuttle Valve is DOWN / 3V3 is OFF
		#Check OFF State
		self.debug_output("selftest: Gate OFF, Phase OFF")
		self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)	#VGate OFF
		self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)	#VPhase OFF
		time.sleep(0.5) #Settling Time after switching relais
		self.GetVGate()
		self.GetVPhase()
		self.GetVSource()

		self.evaluate("VGate", self.VGateDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Gate)
		self.evaluate("VPhase", self.VPhaseDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Phase)
		self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source)

		#Check VGate
		self.SetRelay(Ports.DOUT_VGATE_ON, states.SET)	#VGate ON
		self.debug_output("selftest: Gate ON, Phase OFF")
		
		time.sleep(0.5) #Settling Time after switching relais
		self.GetVGate()
		self.GetVPhase()
		self.GetVSource()
					
		self.evaluate("VGate", self.VGateDUT, 5.65, ERR.TESTER_FAULT, 5.85, ERR.TESTER_FAULT, QGUI.Gate)
		self.evaluate("VPhase", self.VPhaseDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Phase)
		self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source)
			
		#Check VPhase
		self.debug_output("selftest: Gate OFF, Phase ON")
		self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)	#VGate OFF					
		self.SetRelay(Ports.DOUT_VPHASE_ON, states.SET)	#VPhase ON

		time.sleep(0.5) #Settling Time after switching relais
		self.GetVGate()
		self.GetVPhase()
		self.GetVSource()

		self.evaluate("VGate", self.VGateDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Gate)
		self.evaluate("VPhase", self.VPhaseDUT, -8.0, ERR.TESTER_FAULT, -7.7, ERR.TESTER_FAULT, QGUI.Phase)
		self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source)
		
		self.debug_output("selftest: Gate OFF, Phase ON")
		self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)	#VPhase OFF

		#Check OFF State
		time.sleep(0.5) #Settling Time after switching relais
		self.GetVGate()
		self.GetVPhase()
		self.GetVSource()

		self.evaluate("VGate", self.VGateDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Gate)
		self.evaluate("VPhase", self.VPhaseDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Phase)
		self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source)

	def state_machine(self):
		#coming from the constructor, the next (first) state is set:
		self.schedule(STATE.LOGON)
		self.debug_output("state machine: entered")
		#Loop state machine
		
		while 1 == 1:
			#Logon State
			time.sleep(0.1)		#time comes only into effect if the test is paused and self.UserStart is 0
								#this sleep time prevents the  statemachine process from drawing the complete cpu power 
			if self.UserExit == 1:
				#reason: if self.UserStart = 0 (test is haltet, the scheduler isnt called and therefore the self.exit flag not qeried, therefore this has to be done here)
				self.Next_State = STATE.EXIT

				
			if self.Next_State == STATE.LOGON:
				self.debug_output("logon state entered, UserStart var = %i\n" % self.UserStart)
				self.debug_output("Prev_State: %s,\nThis_State: %s,\nNext_State: %s\n" % (repr(self.Prev_State), repr(self.This_State), repr(self.Next_State)))
				
				self.eval_cmdargs()
				if self.LOGON_OK != STATUS.PASSED:
					self.debug_output("login failed\n")
					self.schedule(STATE.LOGON)

				else:
					#Login has been successful
					self.debug_output("login successfull")
					self.schedule(STATE.HALT)		#User Starts Test Process, from HALT state -> INIT state
					self.gui = ShuttleGUI(self.master, self.guiqueue, self.startCommand, self.haltCommand, self.exitCommand, self.gui_shuttlevalve_up, self.gui_shuttlevalve_down, self.gui_vphase_on, self.gui_vphase_off, self.gui_vphase_rev_off, self.gui_vphase_rev_on, self.gui_gate_on, self.gui_vgate_off, self.GetVGate, self.GetVPhase, self.GetVSource)
					#control output
					print("Bitte auf den Start-Knopf Drücken, um den Test zu starten")

			#while self.UserStart == 1 and self.Next_State != STATE.EXIT:
			while self.Next_State != STATE.EXIT:
				#Init State
				#if self.Prev_State == STATE.ENTRY and This_State == STATE.ENTRY and self.Next_State == STATE.INIT:
				if self.Next_State == STATE.INIT:
					#Set Logging File and Path for Selftest
					self.TotalShuttlesTested = 0
					#date: L:\YYYY-MM-DD_Shuttle_XXXX
					#Logging File is set in STATE.TESTING, self.TotalShuttlesTested is increased in STATE.EVALUATE
					self.LoggingFile = "L:\\" + str(date.today()) + "_" + "Init" + ".ascii"
					self.LoggingFile = open(self.LoggingFile, 'w')
		
					#control output
					self.debug_output("Prev_State: %s,\nThis_State: %s,\nNext_State: %s\n" % (repr(self.Prev_State), repr(self.This_State), repr(self.Next_State)))
					self.TESTSTEP = "Init "
					self.LoggingFile.write("%s\n" % self.TESTSTEP)

					#Get Lot Number (Only at the beginning of the test)
					if self.REQ_LOTN == states.SET:
						self.LOTCODE = input('Bitte geben die aktuelle Auftragsnummer ein\n')
						print('Die aktuelle Auftragsnummer lautet:\n%s' % (self.LOTCODE))
					
					#User can only set to PROG_MODE to SERVICE if ACCESS_LEVEL is SERVICE, otherwise PROG_MODE is PRODUCTION
					if self.ACCESS_LEVEL == MODE.PRODUCTION:
						self.PROG_MODE = MODE.PRODUCTION
					self.TIME_TESTSTART = time.localtime()
					self.debug_output("Overview User Data\n\tUserName: %s\n\tAccess Level: %s\n\tProgram Mode: %s\n\tOutput Mode: %s\n\tLogon Datum: %02d.%02d.%4d\n\tUhrzeit: %02d:%02d:%02d\n" % (self.USERNAME, self.ACCESS_LEVEL, self.PROG_MODE, self.OUTPUT_MODE, self.TIME_TESTSTART[2], self.TIME_TESTSTART[1], self.TIME_TESTSTART[0], self.TIME_TESTSTART[3], self.TIME_TESTSTART[4], self.TIME_TESTSTART[5]))
		
					#control output
					self.debug_output("Variables have been initialized")

					#Open Labjack Modules 1 and 2
					if self.LabjacksOpened == states.CLEAR:
						for i in range(0, self.NLJM):
							if self.OpenLabjack(i+1) >= 0:
								self.debug_output("No errors during opening Labjack Module")
								#Setting Tester Status is done after each step in which the correct behavior can be checked
								self.TESTER_STATUS = STATUS.PASSED
								self.debug_output("Labjack Module %i opened, Tester_Status is %s" % (i+1, repr(self.TESTER_STATUS)))
							else:
								self.TESTER_STATUS = STATUS.ERROR
						#set the flag to indicate the Labjacks are opened
					#else:
					#	do nothing, leave the state of self.LabjacksOpened as defined by the constructor

					#------Initialize Tester------------------------------------------------#
					#------Each Time an Actor is controlled the self.TESTER_STATUS might be set to STATUS.ERROR in case of an error
					self.SetRelay(Ports.DOUT_3V3ISO_ON, states.CLEAR)	#3V3ISO OFF
					self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)	#VPhase in Reverse State
					self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)		#Set Shuttle Valve to position down
					self.SetRelay(Ports.STOPPER_VALVE, position.DOWN)	#Set StopperValve to position down (let Shuttles pass)
					#------Initialize Tester Status------------------------------------------------#

					self.selftest() #selftest keeps the relay settings after it is finished

					self.LoggingFile.close()	#close logging file for init after selftest
					
					#start periodic execution of the gui which is polled cyclical via the function processIncoming which is called from the InlineStateMachine
					self.periodicCall()
					setcounter = 0		#anti glitch counter in idle state, has to be initialized here to avoid unwanted resetting
					self.schedule(STATE.IDLE)
				
				if self.Next_State == STATE.IDLE:		#use of setcounter avoids that a single (erratic) impulse triggers the test
					#MAXWAITCYC = 5	#Only in automatic mode: Wait cycles, for which the SHUTTLE_AVLBL signnal has to be low to begin testing
					MAXWAITCYC = 1	#in manual mode: Wait cycles, for which the SHUTTLE_AVLBL signnal has to be low to begin testing
					CYCTIME = 0.1
					#Since Idle State is calling itself, the STATE GETSN has to be within the idle state
					if self.REQ_SN == states.SET and self.SERIAL == "0":
						self.schedule(STATE.GETSN)
					
					#Check Serial Number
					if self.Next_State == STATE.GETSN:
						#Get Serial Number if enabled in command line args
						#Serial Number is set to default value "0" after Evaluation
						self.SERIAL = input('Eine Seriennummer aus dem aktuellen, zu testenden Shuttle einscannen\n')
						print('die Seriennummer lautet: %s\n' % (self.SERIAL))
						print('Nun auf beide seitlichen Taster drücken,\nbis das Shuttle am Anschlag ist\n')
						self.schedule(STATE.IDLE)
						
					if self.GetRelay(Ports.SHUTTLE_AVLBL) == states.CLEAR: #SHUTTLE_AVLBL is low active 
						self.debug_output("Inline Test: a shuttle is now available\n Test will be started")
						
						setcounter += 1
						time.sleep(CYCTIME)
					else:
						self.debug_output("Inline Test: waiting for a shuttle\n")
						self.schedule(STATE.IDLE)
						time.sleep(0.5)
						setcounter = 0		#reset setcounter e.g. after a glitch
					if setcounter == MAXWAITCYC:
						self.SetRelay(Ports.STOPPER_VALVE, position.UP)	#Set StopperValve to position up (stop Shuttles)
						setcounter = 0
						StepIndex = 0			#Number of Test Steps, for Protokoll
						self.schedule(STATE.TESTING)
				
			
				if self.Next_State == STATE.TESTING:
					SettlingTime = 0.3
					StepIndex += 1			#current Test Step, for Protokoll, init in the state before TESTING, currently this is IDLE
					#time.sleep(2)			#only in automatic mode: wait for shuttle to reach index position after Stopper went up
					#Temp variables to store the error codes after each DUT Test step
					GateErrorT4 = list(range(0, NDUT))
					GateErrorT5 = list(range(0, NDUT))
					PhaseErrorT3 = list(range(0, NDUT))
					SourceErrorT3 = list(range(0, NDUT))
					SourceErrorT4 = list(range(0, NDUT))
					SourceErrorT5 = list(range(0, NDUT))
					SourceErrorT6 = list(range(0, NDUT))
					
	
					self.qObj[QGUI.Dutstati_Old] = self.DUTSTATUSMEM	#Index with the errorcodes
					if self.guiqueue.qsize() < self.QMAXSIZE:
						self.guiqueue.put(self.qObj)
				
					for i in range(0, NDUT):
						GateErrorT4[i] = ERR.NORES
						GateErrorT5[i] = ERR.NORES
						PhaseErrorT3[i] = ERR.NORES
						SourceErrorT3[i] = ERR.NORES
						SourceErrorT4[i] = ERR.NORES
						SourceErrorT5[i] = ERR.NORES
						SourceErrorT6[i] = ERR.NORES

	
					#shift DUTSTATUS in memory
					#older self.DUTSTATUS-data is shifted back
					for m in range(0, MEMCYC-1):
						for i in range(0, NDUT):	
							self.DUTSTATUSMEM[(MEMCYC-m-1)*NDUT + i] = self.DUTSTATUSMEM[(MEMCYC-m-2)*NDUT + i]
					#m = 0 for DUTSTATUS N-1, 
					#last shuttle gets self.DUTSTATUS from current shuttle at beginning of the next test
					#this assignment has to be done after all the old data has been shifted
					#after this assignment self.DUTSTATUS of the current test is set to NORES
					for i in range(0, NDUT):		
						self.DUTSTATUSMEM[i] = self.DUTSTATUS[i]
						#set current DUTRESULT to NORES
						self.DUTSTATUS[i] = ERR.NORES

					self.TotalShuttlesTested = self.TotalShuttlesTested + 1
					#date: L:\YYYY-MM-DD_Shuttle_XXXX
					self.LoggingFile = "L:\\" + str(date.today()) + "_" + "Shuttle_" + str(self.TotalShuttlesTested) + ".ascii"
					print("The Logging File is: %s " % self.LoggingFile)
					self.LoggingFile = open(self.LoggingFile, 'w')
					

					
					self.TIME_RUNSTART = time.time()	#Get Start Time (seconds till epoch 1.1.1970) as float  
					#-----------------------------------TS001----------------------------------------------------------------------------
					self.TESTSTEP = "TS" + str(StepIndex) + " - Selftest1: "
					self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)		#Set Shuttle Valve to position down
					self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)		#VPhase OFF
					self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)	#VPhase in Reverse State
					self.SetRelay(Ports.DOUT_VGATE_ON, states.SET)			#VGate ON
					time.sleep(SettlingTime)					
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()

					#if any of these voltages is out of range evaluate(...) sets TESTER_STATUS to STATUS.FAIL
					#possible causes for voltages being out of range: voltage supply off, Labjack Module defective / not connected
					self.evaluate("VGate", self.VGateDUT, 5.65, ERR.TESTER_FAULT, 5.85, ERR.TESTER_FAULT, QGUI.Gate)
					self.evaluate("VPhase", self.VPhaseDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source) #determine whether Source is connected
					
					self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)			#VGate OFF
					
					#------------------------------------TS002-------------------------------------------------------------------------
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Selftest2: "
					self.SetRelay(Ports.DOUT_VPHASE_ON, states.SET)				#VPhase ON

					time.sleep(SettlingTime)
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()

					self.evaluate("VGate", self.VGateDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Gate)
					self.evaluate("VPhase", self.VPhaseDUT, -8.0, ERR.TESTER_FAULT, -7.6, ERR.TESTER_FAULT, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source) #determine whether Source is connected

					self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)				#VPhase OFF
					


					#-------------------------------------TS003--------------------------------------------------------------------------------
					#-----------This test step determines:
					#-----------Needle Connection Phase, Source (and Gate) to DCB (Only a fault can be detected but not which one of the needle pairs caused the fault)
					#-----------Source wire not bonded 
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Phase Reverse: "
					self.SetRelay(Ports.SHUTTLE_VALVE, position.UP)		#Set Shuttle Valve to position up
					time.sleep(SettlingTime*2)							#additional wait time for ESD safety to make sure the VGate is only applied after all needle contacted
					self.SetRelay(Ports.DOUT_VPHASE_ON, states.SET)		#VPhase ON, Rev Mode activated in previous tests

					time.sleep(SettlingTime*5)							#additional wait time for ESD safety to make sure the VGate is only applied after all needle contacted	#Sufficient wait time after shuttle has reached its upper position is mandatory to avoid pseudo errors (contact of gate-needle / source needle is not recognized)
				
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()
					
					self.evaluate("VGate", self.VGateDUT, -0.200, ERR.VLOW, -0.170, ERR.VHIGH, QGUI.Gate)
					self.evaluate("VPhase", self.VPhaseDUT, -7.6, ERR.VLOW, -7.4, ERR.VHIGH, QGUI.Phase)
					#evaluate() writes the result with the error codes to DUTSTATUSTMP
					#to copy the error codes prior to the next evaluation (which would overwrite the old results)
					#copy has to be done index wise and not GateErrorT4 = self.DUTSTATUSTMP this would merely make GateErrorT4 a reference to DUTSTATUSTMP and the info about the current test would be lost
					for i in range(0, NDUT):
						PhaseErrorT3[i] = self.DUTSTATUSTMP[i]	#Assign DUTSTATUS with Phase Errors to temporary list to validate error patterns in STATE.EVALUATE

					self.evaluate("VSource", self.VSourceDUT, -0.77, ERR.VLOW, -0.57, ERR.VHIGH, QGUI.Source)
					for i in range(0, NDUT):
						SourceErrorT3[i] = self.DUTSTATUSTMP[i]	#Assign DUTSTATUS with Source Errors to temporary list to validate error patterns in STATE.EVALUATE

					time.sleep(SettlingTime)										

					self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)		#VPhase OFF

					#-------------------------------------TS004--------------------------------------------------------------------------------
					#-----------This test step determines:
					#-----------Gate and Source needle connection to DCB (it can't be differntiated between a fault of one or both of these needle pairs)
					#-----------Gate Source functioning: Tomb Stone of Gate-Source Short, R1/2/3, Gate not bonded (Tomb Stone and Not-Bonded can't be differtiated in this step allone)
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Fct G-ON Ph-OFF: "
					self.SetRelay(Ports.DOUT_VGATE_ON, states.SET)			#VGate ON
					
					time.sleep(SettlingTime)
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()
					
					self.evaluate("VGate", self.VGateDUT, 5.1, ERR.VLOW, 5.35, ERR.VHIGH, QGUI.Gate)
					for i in range(0, NDUT):
						GateErrorT4[i] = self.DUTSTATUSTMP[i]
					self.evaluate("VPhase", self.VPhaseDUT, 0.01, ERR.VLOW, 0.07, ERR.VHIGH, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, 0.06, ERR.VLOW, 0.08, ERR.VHIGH, QGUI.Source) #determine whether Source is connected
					for i in range(0, NDUT):
						SourceErrorT4[i] = self.DUTSTATUSTMP[i]
					
					#-------------------------------------TS005--------------------------------------------------------------------------------
					#-----------This test step determines:
					#-----------DUT Function (even if a GS-short was detected, this test is performed): Gate-Source Function, Drain-Source Function, Bonded / Not Bonded
					
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Fct G-ON Ph-ON: "

					self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.SET)	#VPhase Reverse OFF
					self.SetRelay(Ports.DOUT_VPHASE_ON, states.SET)		#VPhase ON

					time.sleep(SettlingTime)															
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()
					
					self.evaluate("VGate", self.VGateDUT, 5.19, ERR.VLOW, 5.4, ERR.VHIGH, QGUI.Gate)
					for i in range(0, NDUT):
						GateErrorT5[i] = self.DUTSTATUSTMP[i]
					self.evaluate("VPhase", self.VPhaseDUT, 7.35, ERR.VLOW, 7.65, ERR.VHIGH, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, 0.70, ERR.VLOW, 0.83, ERR.VHIGH, QGUI.Source)
					for i in range(0, NDUT):
						SourceErrorT5[i] = self.DUTSTATUSTMP[i]

					#-------------------------------------TS006--------------------------------------------------------------------------------
					#-----------This test step determines:
					#-----------Drain Source Function Test / DUT in OFF State 
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Fct G-OFF Ph-ON: "

					self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)			#VGate OFF

					time.sleep(SettlingTime)										
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()
					
					self.evaluate("VGate", self.VGateDUT, 0.055, ERR.VLOW, 0.085, ERR.VHIGH, QGUI.Gate)
					self.evaluate("VPhase", self.VPhaseDUT, 7.65, ERR.VLOW, 7.9, ERR.VHIGH, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, 0.14, ERR.VLOW, 0.18, ERR.VHIGH, QGUI.Source)
					for i in range(0, NDUT):
						SourceErrorT6[i] = self.DUTSTATUSTMP[i]

					#-------------------------------------TS007--------------------------------------------------------------------------------
					StepIndex += 1			#Number of Test Steps, for Protokoll
					self.TESTSTEP = "TS" + str(StepIndex) + " - Fct G-OFF Ph-OFF: "

					self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)		#VPhase OFF
					self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)	#VPhase Reverse, prepare to finish testing

					time.sleep(SettlingTime)										
					
					self.GetVGate()
					self.GetVPhase()
					self.GetVSource()
					
					self.evaluate("VGate", self.VGateDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Gate)
					self.evaluate("VPhase", self.VPhaseDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Phase)
					self.evaluate("VSource", self.VSourceDUT, -0.03, ERR.TESTER_FAULT, 0.03, ERR.TESTER_FAULT, QGUI.Source)

					#----------------------------------Test Finished-----------------------------------------------------------------------------
					self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)	#VGate OFF
					self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)	#VPhase OFF
					self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)	#VPhase in Reverse State

					self.SetRelay(Ports.STOPPER_VALVE, position.DOWN)		#1. Remove Stopper
					self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)		#2. Set Shuttle Valve to position down
				
					self.debug_output("test finished")

					#Wait until shuttle is passed the inductive sensor before going to IDLE state, 
					#so that the SHUTTLE_AVLBL signal isn't set by the already tested shuttle
					SHUTTLE_TRANSIT_TIME = 0.5		#constant / variable assignment just for code readability
					time.sleep(SHUTTLE_TRANSIT_TIME)

					#Get Stop time, this step might have to be moved to STATE.EVALUATE
					self.TIME_RUNSTOP = time.time()	#Get Start Time (seconds till epoch 1.1.1970) as float  
					
					print("Total test time was: %2.2f sec" % (self.TIME_RUNSTOP - self.TIME_RUNSTART))
					
					for i in range(0,NDUT):
						self.debug_output("STATE.TESTING: GateErrorT4 Mo %i is %s" % (i+1, repr(GateErrorT4[i])))
					
					#Go to Evaluation
					self.schedule(STATE.EVALUATE)

				if self.Next_State == STATE.HALT:
					time.sleep(1) #wait a little longer, so the gui can be updated
					self.debug_output("Inline statemachine: in halt mode")
					
				
					#poll UserStart flag
					if self.UserStart == 1:
						self.Next_State = STATE.INIT
					else:
						self.Next_State = STATE.HALT
				
					self.schedule(self.Next_State)
					
				if self.Next_State == STATE.EVALUATE:
					#evaluation of the errors occurred during STATE.TESTING
					#the evaluation includes only the DUT-relevant test steps (possible errors are Voltage high / low) 
					#and not those which evaluate the tester (possible error code is ERR.TESTER_FAULT)
		
					for i in range(0,NDUT): 	#sample the test results of each step and each DUT
						self.TotalDUTsTested += 1		#Bonded and unbonded DUTs
						if PhaseErrorT3[i] == ERR.PASSED and SourceErrorT3[i] == ERR.PASSED and GateErrorT4[i] == ERR.PASSED and SourceErrorT5[i] == ERR.PASSED  and SourceErrorT6[i] == ERR.PASSED:
							self.DUTSTATUS[i] = ERR.PASSED
							self.TotalDUTsPassed += 1
						elif GateErrorT4[i] == ERR.VLOW and SourceErrorT4[i] == ERR.VHIGH and GateErrorT5[i] == ERR.VLOW:
							self.DUTSTATUS[i] = ERR.GS_SHORT
							self.TotalDUTsFailed += 1
							self.TotalDUTsGSShort += 1
						elif PhaseErrorT3[i] == ERR.VLOW and SourceErrorT3[i] == ERR.VHIGH and SourceErrorT5[i] == ERR.VLOW:
							self.DUTSTATUS[i] = ERR.NOT_BONDED
							self.TotalDUTsNotBonded += 1
							#dont increase TotalDUTsTested counter: the number of unbonded parts can be calculated by: total - passed - failed
						elif SourceErrorT6[i] == ERR.VHIGH:
							self.DUTSTATUS[i] = ERR.DS_SHORT
							self.TotalDUTsFailed += 1
							self.TotalDUTsDSShort += 1
						else:
							self.DUTSTATUS[i] = ERR.UNKNOWN
							self.TotalDUTsFailed += 1
						self.LoggingFile.write('Auftragsnummer: %s\n' % (self.LOTCODE))
						self.LoggingFile.write('Ausgewählte SN: %s\n' % (self.SERIAL))
						
						self.LoggingFile.write("DUT Error Code Module%i: %i\n" % (i+1, self.DUTSTATUS[i]))

					#put statistics to LoggingFile if verbose mode is enabled (self.OUTPUT_MODE = MODE.DEBUG)
					if self.OUTPUT_MODE == MODE.DEBUG:
						self.LoggingFile.write("\n")
						self.LoggingFile.write("Statistics:\n")
						self.LoggingFile.write("Total DUTs Passed %i\n" % self.TotalDUTsPassed)
						self.LoggingFile.write("Total DUTs Failed %i\n" % self.TotalDUTsFailed)
						self.LoggingFile.write("Total DUTs with GS-Short %i\n" % self.TotalDUTsGSShort)
						self.LoggingFile.write("Total DUTs with DS-Short %i\n" % self.TotalDUTsDSShort)
						self.LoggingFile.write("Total DUTs not bonded %i\n" % self.TotalDUTsNotBonded)
					#write Testtime to LoggingFile
					self.LoggingFile.write("Total test time: %2.2f sec" % (self.TIME_RUNSTOP - self.TIME_RUNSTART))
					self.LoggingFile.close()		#close logging file after all date has been stored
					
					#Reset serial number to default value so that the input is done once if self.REQ_SN was set in cmd_args
					if self.REQ_SN == states.SET:
						self.SERIAL = "0"
					
					#Check if an error occured repeatadely for MEMCYC (default 3) times in succession
					for i in range(0, NDUT):
						#Reset counter restmp each time a new module is checked for repetition error
						restmp = 0
						#The Repetition error includes only Test fails (not NORES and not PASS), optional: not bonded parts could be excluded if there are too many
						if (self.DUTSTATUS[i] != ERR.PASSED) and (self.DUTSTATUS[i] != ERR.NORES): #and (self.DUTSTATUS[i] != ERR.NOT_BONDED):
							for m in range(0, MEMCYC-1):
								if(self.DUTSTATUSMEM[m*NDUT + i] == self.DUTSTATUS[i]):
									restmp = restmp + 1 
									self.debug_output("Repetition Error m = %i" % m)

						#Tester-Error problably in Needle adapter
						#self.TESTER_STATUS = STATUS.ERROR
						if restmp == MEMCYC-1:
							#Tester-Status is set to Error at the first occurrance of a repetition error 
							#root cause might be a the Needle adapter (needle fault, cable connection, power supply, etc.)
							self.TESTER_STATUS = STATUS.ERROR
							self.debug_output("Repetition Error: Position %i is %s" % (i+1, repr(self.TESTER_STATUS)))

						
					
					for i in range(0,NDUT):
						self.debug_output("STATE.EVALUATE: GateErrorT4 Mo %i is %s" % (i+1, repr(GateErrorT4[i])))

					#write result to GUI-queue
					self.qObj[QGUI.Dutstatus] = self.DUTSTATUS	#Index with the errorcodes
					self.qObj[QGUI.Ntot] = self.TotalDUTsTested
					self.qObj[QGUI.Npass] = self.TotalDUTsPassed
					self.qObj[QGUI.Nfail] = self.TotalDUTsFailed
					self.qObj[QGUI.Ngs_short] = self.TotalDUTsGSShort
					self.qObj[QGUI.Nnot_bonded] = self.TotalDUTsNotBonded
					self.qObj[QGUI.Nds_short] = self.TotalDUTsDSShort
					
					self.guiqueue.put(self.qObj)
					
					#Go to idle state and Wait for next shuttle
					self.schedule(STATE.IDLE)

			if self.Next_State == STATE.EXIT:
				#close the Labjack Modules only if they have been opened
				if self.LabjacksOpened == states.SET:
					self.CloseLabjack(1)	#Close Labjack Module 1
					self.CloseLabjack(2)	#Close Labjack Module 2
				#clean up...
				self.SetRelay(Ports.DOUT_3V3ISO_ON, states.CLEAR)	#3V3ISO OFF
				self.SetRelay(Ports.DOUT_VGATE_ON, states.CLEAR)	#VGate OFF
				self.SetRelay(Ports.DOUT_VPHASE_ON, states.CLEAR)	#VPhase OFF
				self.SetRelay(Ports.DOUT_VPHASE_REV_OFF, states.CLEAR)	#VPhase in Reverse State
				self.SetRelay(Ports.SHUTTLE_VALVE, position.DOWN)		#Set Shuttle Valve to position down
				self.SetRelay(Ports.STOPPER_VALVE, position.DOWN)	#Set StopperValve to position down (let Shuttles pass)

				self.debug_output("Inline statemachine: exit code executed")
				self.master.destroy()
				sys.exit(1)			


root = tkinter.Tk()
InlineTest = InlineStateMachine(root)
print("Test has been started")		
root.mainloop()
print("Test has been stopped")		
#------------------------------------------------------------------------Inline Tester State Machine-----------------------------------------------------------------------
