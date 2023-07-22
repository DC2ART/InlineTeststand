from InlineClasses import MODE, STATUS, ERR, QGUI, NDUT, MEMCYC
import re, tkinter, os, unicodedata, time

class ShuttleGUI:
	"""
	tkinter is not threadsafe therefore the Inline statemachine and the Inline GUI share data via a queue
	the queue is a class member of the statemachine class
	the statemachine hands the queue over to the gui
	the statemachine initializes an update in the gui by starting the function processIncoming
	"""
	def __init__(self, Inmaster, inqueue, startTest, haltTest, exitTest, shuttle_up, shuttle_down, vphase_on, vphase_off, vphase_rev_off, vphase_rev_on, vgate_on, vgate_off, get_vgate, get_vphase, get_vsource):
		self.master = Inmaster
		self.master.title("Inline Function Test SSSPR")
		self.queue = inqueue
		self.qObj = self.queue.get(0)
		self.GateList = self.qObj[QGUI.Gate]
		self.PhaseList = self.qObj[QGUI.Phase]
		self.SourceList = self.qObj[QGUI.Source]
		self.EvalRes = self.qObj[QGUI.Dutstatus]	#DUT Status of current Shuttle
		self.EvalRes_Old = self.qObj[QGUI.Dutstati_Old] #DUT Stati of old Shuttles
		self.TesterState = self.qObj[QGUI.TesterState]
		self.Ntot = self.qObj[QGUI.Ntot]
		self.Npass = self.qObj[QGUI.Npass]
		self.Nfail = self.qObj[QGUI.Nfail]
		self.Ngs_short = self.qObj[QGUI.Ngs_short]
		self.Nnot_bonded = self.qObj[QGUI.Nnot_bonded]
		self.Nds_short = self.qObj[QGUI.Nds_short]
		self.State = self.qObj[QGUI.State]
		self.PRG_MODE = self.qObj[QGUI.Mode]

		row = 3	#rows in a shuttle
		col = 3 #colums in a shuttle

		#DUT Status of Shuttle N-1 (= last shuttle) ... N-3 (3 shuttles ago)
		self.EvalResN1 = list(range(0, NDUT))
		self.EvalResN2 = list(range(0, NDUT))
		self.EvalResN3 = list(range(0, NDUT))
		
		#Buttons for Service and Production have different positions (and sizes) 
		#but the names must remain the same for both modes (for updating values / colours)
		#Buttons for Service Mode
		if self.PRG_MODE == MODE.SERVICE:
			self.console = list(range(0, NDUT))	#Shuttle Overview for the results
			PADx = 5	#Space in x-dir between labels
			PADy = 5	#Space in y-dir between labels
			Lwidth = 20	#Width of Labels
			Lheight = 6	#Hight of Labels
			for r in range(0, row):
				for c in range(0, col):
					index = int(r*row + c + 1)
					self.console[index-1] = tkinter.Label(Inmaster, text="Init", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
					self.console[index-1].grid(row=r, column=c, sticky="N", pady=PADy, padx = PADx)
			self.stat_tot = tkinter.Label(Inmaster, text = "DUTs TOTAL: ", bg = "yellow", fg = "black", width = Lwidth, height = Lheight)
			self.stat_tot.grid(row=0, column=4, sticky="N", pady=PADy, padx = 2*PADx)
			self.stat_pass = tkinter.Label(Inmaster, text = "DUTs PASSED: ", bg = "green", fg = "white", width = Lwidth, height = Lheight)
			self.stat_pass.grid(row=1, column=4, sticky="N", pady=PADy, padx = 2*PADx)
			self.stat_fail = tkinter.Label(Inmaster, text = "DUTs FAILED: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
			self.stat_fail.grid(row=2, column=4,  sticky="N", pady=PADy, padx =2*PADx)
			self.stat_gsshort = tkinter.Label(Inmaster, text = "DUTs GS Short: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
			self.stat_gsshort.grid(row=3, column=4,  sticky="N", pady=PADy, padx =2*PADx)
			self.stat_dsshort = tkinter.Label(Inmaster, text = "DUTs DS Short: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
			self.stat_dsshort.grid(row=4, column=4,  sticky="N", pady=PADy, padx =2*PADx)
			self.stat_notbonded = tkinter.Label(Inmaster, text = "DUTs Not Bonded: ", bg = "blue", fg = "white", width = Lwidth, height = Lheight)
			self.stat_notbonded.grid(row=5, column=4,  sticky="N", pady=PADy, padx =2*PADx)				
			self.tst_status = tkinter.Label(Inmaster, text = "TESTER STATUS", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
			self.tst_status.grid(row=0, column=3,  sticky="N", pady=PADy, padx =2*PADx)				
			self.state_lbl = tkinter.Label(Inmaster, text = "TESTER STATE:", bg = "white", fg = "black", width = Lwidth, height = Lheight)
			self.state_lbl.grid(row=1, column=3,  sticky="N", pady=PADy, padx =2*PADx)

				
			#----------------------Start Programm--------------------------------------------------------------------------------------------				
			self.startbutton = tkinter.Button(Inmaster, text="Start Test", command=startTest, width = Lwidth, height = Lheight)
			self.startbutton.grid(row=3, column=0,  sticky="N", pady=PADy, padx =PADx)		
			#----------------------Stop Programm--------------------------------------------------------------------------------------------
			self.stopbutton = tkinter.Button(Inmaster, text="Halt Test", command=haltTest, width = Lwidth, height = Lheight)
			self.stopbutton.grid(row=3, column=1,  sticky="N", pady=PADy, padx =PADx)
			#----------------------Exit Programm--------------------------------------------------------------------------------------------
			self.exitbutton = tkinter.Button(Inmaster, text="Exit Test", command=exitTest, width = Lwidth, height = Lheight)
			self.exitbutton.grid(row=3, column=2,  sticky="N", pady=PADy, padx =PADx)
		
			#-----------------------Move Shuttle--------------------------------------------------------------------------------------------
			self.shuttleup_button = tkinter.Button(Inmaster, text="Shuttle Up", command=shuttle_up, width = Lwidth, height = Lheight)
			self.shuttleup_button.grid(row=4, column=0,  sticky="N", pady=PADy, padx =PADx)

			self.shuttledown_button = tkinter.Button(Inmaster, text="Shuttle Down", command=shuttle_down, width = Lwidth, height = Lheight)
			self.shuttledown_button.grid(row=4, column=1,  sticky="N", pady=PADy, padx =PADx)
			#-----------------------Move Shuttle--------------------------------------------------------------------------------------------
		
			#-----------------------VPhase ON / OFF, REV OFF / REV ON, GET-------------------------------------------------------------------
			self.vphaseon_button = tkinter.Button(Inmaster, text="VPhase On", command=vphase_on, width = Lwidth, height = Lheight)
			self.vphaseon_button.grid(row=5, column=0,  sticky="N", pady=PADy, padx =PADx)

			self.vphaseoff_button = tkinter.Button(Inmaster, text="VPhase Off", command=vphase_off, width = Lwidth, height = Lheight)
			self.vphaseoff_button .grid(row=5, column=1,  sticky="N", pady=PADy, padx =PADx)

			self.vphaserevoff_button = tkinter.Button(Inmaster, text="VPhase Rev Off", command=vphase_rev_off, width = Lwidth, height = Lheight)
			self.vphaserevoff_button.grid(row=5, column=2,  sticky="N", pady=PADy, padx =PADx)

			self.vphaserevon_button = tkinter.Button(Inmaster, text="VPhase Rev On", command=vphase_rev_on, width = Lwidth, height = Lheight)
			self.vphaserevon_button.grid(row=4, column=2,  sticky="N", pady=PADy, padx =PADx)		
		
			self.getphase_button = tkinter.Button(Inmaster, text="Get VPhase", command=get_vphase, width = Lwidth, height = Lheight)
			self.getphase_button.grid(row=7, column=2,  sticky="N", pady=PADy, padx =PADx)						
			#-----------------------VPhase ON / OFF, REV OFF / REV ON, GET-------------------------------------------------------------------
		
			#----------------------VGate ON / OFF, GET----------------------------------------------------------------------------------------		
			self.vgateon_button = tkinter.Button(Inmaster, text="VGate On", command=vgate_on, width = Lwidth, height = Lheight)
			self.vgateon_button.grid(row=6, column=0,  sticky="N", pady=PADy, padx =PADx)				
		
			self.vgateoff_button = tkinter.Button(Inmaster, text="VGate Off", command=vgate_off, width = Lwidth, height = Lheight)
			self.vgateoff_button.grid(row=6, column=1,  sticky="N", pady=PADy, padx =PADx)				
		
			self.getphase_button = tkinter.Button(Inmaster, text="Get VGate", command=get_vgate, width = Lwidth, height = Lheight)
			self.getphase_button.grid(row=6, column=2,  sticky="N", pady=PADy, padx =PADx)						
			#----------------------VGate ON / OFF, GET----------------------------------------------------------------------------------------
		
			self.getsource_button = tkinter.Button(Inmaster, text="Get VSource", command=get_vsource, width = Lwidth, height = Lheight)
			self.getsource_button.grid(row=7, column=0,  sticky="N", pady=PADy, padx =PADx)						
		
		#Buttons for Production mode
		if self.PRG_MODE == MODE.PRODUCTION:
			row = 3
			col = 3
			self.console = list(range(0, row*col))	#Shuttle Overview for the results
			PADx = 5	#Space in x-dir between labels
			PADy = 5	#Space in y-dir between labels
			Lwidth = 20	#Width of Labels
			Lheight = 6	#Hight of Labels
			
			self.console = list(range(0, row*col))		#Result overview for the current shuttle
			#											#Result overview in Production mode for the
			self.consoleN1 = list(range(0, row*col))	# 	first before the current shuttle 	(N-1) 
			self.consoleN2 = list(range(0, row*col))	# 	second before the current shuttle 	(N-2) 
			self.consoleN3 = list(range(0, row*col))	# 	third before the current shuttle 	(N-3) 

			PADx = 5	#Space in x-dir between labels
			PADy = 5	#Space in y-dir between labels
			Lwidth = 20	#Width of Labels
			Lheight = 6	#Hight of Labels

			for r in range(0, row):
				for c in range(0, col):
					index = int(r*row + c + 1)
					self.console[index-1] = tkinter.Label(Inmaster, text="Init", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
					self.console[index-1].grid(row=r, column=c, sticky="N", pady=PADy, padx = PADx)
					
					self.consoleN1[index-1] = tkinter.Label(Inmaster, text="Init", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
					self.consoleN1[index-1].grid(row=r, column=c+4, sticky="N", pady=PADy, padx = PADx)
					
					self.consoleN2[index-1] = tkinter.Label(Inmaster, text="Init", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
					self.consoleN2[index-1].grid(row=r+3, column=c+4, sticky="N", pady=PADy, padx = PADx)
					
					self.consoleN3[index-1] = tkinter.Label(Inmaster, text="Init", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
					self.consoleN3[index-1].grid(row=r+6, column=c+4, sticky="N", pady=PADy, padx = PADx)					

				self.N1lbl = tkinter.Label(Inmaster, text = "Shuttle N-1: ", bg = "grey", fg = "white", width = Lwidth, height = Lheight)
				self.N1lbl.grid(row=0, column=3, sticky="N", pady=PADy, padx = 2*PADx)

				self.N2lbl = tkinter.Label(Inmaster, text = "Shuttle N-2: ", bg = "grey", fg = "white", width = Lwidth, height = Lheight)
				self.N2lbl.grid(row=3, column=3, sticky="N", pady=PADy, padx = 2*PADx)
				
				self.N3lbl = tkinter.Label(Inmaster, text = "Shuttle N-3: ", bg = "grey", fg = "white", width = Lwidth, height = Lheight)
				self.N3lbl.grid(row=6, column=3, sticky="N", pady=PADy, padx = 2*PADx)				
				
				self.tst_status = tkinter.Label(Inmaster, text = "TESTER STATUS", bg = "yellow", fg = "white", width = Lwidth, height = Lheight)
				self.tst_status.grid(row=0, column=7,  sticky="N", pady=PADy, padx =2*PADx)				
				self.state_lbl = tkinter.Label(Inmaster, text = "TESTER STATE:", bg = "white", fg = "black", width = Lwidth, height = Lheight)
				self.state_lbl.grid(row=1, column=7,  sticky="N", pady=PADy, padx =2*PADx)
				self.stat_tot = tkinter.Label(Inmaster, text = "DUTs TOTAL: ", bg = "yellow", fg = "black", width = Lwidth, height = Lheight)
				self.stat_tot.grid(row=3, column=7, sticky="N", pady=PADy, padx = 2*PADx)
				self.stat_pass = tkinter.Label(Inmaster, text = "DUTs PASSED: ", bg = "green", fg = "white", width = Lwidth, height = Lheight)
				self.stat_pass.grid(row=4, column=7, sticky="N", pady=PADy, padx = 2*PADx)
				self.stat_fail = tkinter.Label(Inmaster, text = "DUTs FAILED: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
				self.stat_fail.grid(row=5, column=7,  sticky="N", pady=PADy, padx =2*PADx)
				self.stat_gsshort = tkinter.Label(Inmaster, text = "DUTs GS Short: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
				self.stat_gsshort.grid(row=6, column=7,  sticky="N", pady=PADy, padx =2*PADx)
				self.stat_dsshort = tkinter.Label(Inmaster, text = "DUTs DS Short: ", bg = "red", fg = "black", width = Lwidth, height = Lheight)
				self.stat_dsshort.grid(row=7, column=7,  sticky="N", pady=PADy, padx =2*PADx)
				self.stat_notbonded = tkinter.Label(Inmaster, text = "DUTs Not Bonded: ", bg = "blue", fg = "white", width = Lwidth, height = Lheight)
				self.stat_notbonded.grid(row=8, column=7,  sticky="N", pady=PADy, padx =2*PADx)				


				
				#----------------------Start Programm--------------------------------------------------------------------------------------------				
				self.startbutton = tkinter.Button(Inmaster, text="Start Test", command=startTest, width = Lwidth, height = Lheight)
				self.startbutton.grid(row=8, column=0,  sticky="N", pady=PADy, padx =PADx)		
				#----------------------Stop Programm--------------------------------------------------------------------------------------------
				self.stopbutton = tkinter.Button(Inmaster, text="Halt Test", command=haltTest, width = Lwidth, height = Lheight)
				self.stopbutton.grid(row=8, column=1,  sticky="N", pady=PADy, padx =PADx)
				#----------------------Exit Programm--------------------------------------------------------------------------------------------
				self.exitbutton = tkinter.Button(Inmaster, text="Exit Test", command=exitTest, width = Lwidth, height = Lheight)
				self.exitbutton.grid(row=8, column=2,  sticky="N", pady=PADy, padx =PADx)
		#Buttons for Service and Production 
			
	#ResVec contains pass / fail for each DUT (of current shuttle, N-1, N-2, N-3, etc. shuttle)
	#UpGrid is the Label-Grid whose colours, values etc. are to be updated ( current shuttle, N-1, N-2, N-3, etc. shuttle)
	def UpdConLbl(self, ResVec, UpGrid):
		row = 3
		col = 3
		for r in range(0, row):
			for c in range(0, col):
				index = int(r*row + c + 1)

				#switch indices because of maeander index in shuttle
				if (r*row + c + 1) == 4:
					index = 6
				elif (r*row + c + 1) == 6:
					index = 4
				#Shuttle Positions
				# 1 / 2 / 3
				# 6 / 5 / 4
				# 7 / 8 / 9

				#Label Positions
				# 1 / 2 / 3
				# 6 / 5 / 4
				# 7 / 8 / 9				
				# -> for compatible positions, Label Positions 4 and 6 have to be switched
				
				if ResVec[index-1] == ERR.PASSED:
					c_back = "green"	#background colour
				elif ResVec[index-1] == ERR.NOT_BONDED:
					c_back = "blue"		#background colour
				elif ResVec[index-1] == ERR.NORES:
					c_back = "grey"
				else:
					c_back = "red"

				UpGrid[r*row + c].configure(text ="\nMo%i\nError Code: %i" % (index, ResVec[index-1]))
				UpGrid[r*row + c].configure(bg = c_back)

	
	def processIncoming(self):
		"""
		Function is called periodically
		job: Update Inline Test data by getting the qObject out of the queue, assigning it to the correct variable
		and after that update the display
		"""
		row = 3
		col = 3
		
		while not self.queue.empty():
			msg = self.queue.get(0)
			self.GateList = msg[QGUI.Gate]
			self.PhaseList = msg[QGUI.Phase]
			self.SourceList = msg[QGUI.Source]
			self.EvalRes = msg[QGUI.Dutstatus]
			self.EvalRes_Old = msg[QGUI.Dutstati_Old]
			self.TesterState = msg[QGUI.TesterState]
			self.Ntot = msg[QGUI.Ntot]
			self.Npass = msg[QGUI.Npass]
			self.Nfail = msg[QGUI.Nfail]
			self.Ngs_short = self.qObj[QGUI.Ngs_short]
			self.Nnot_bonded = self.qObj[QGUI.Nnot_bonded]
			self.Nds_short = self.qObj[QGUI.Nds_short]			
			self.State = self.qObj[QGUI.State]
			self.PRG_MODE = self.qObj[QGUI.Mode]

		#Update the Error Vectors
		if self.PRG_MODE == MODE.PRODUCTION:
			for i in range(0, NDUT):
				self.EvalResN1[i] = self.EvalRes_Old[i]
			for i in range(NDUT, 2*NDUT):
				self.EvalResN2[i-NDUT] = self.EvalRes_Old[i]
			for i in range(2*NDUT, 3*NDUT):
				self.EvalResN3[i-2*NDUT] = self.EvalRes_Old[i]
				
			self.UpdConLbl(self.EvalResN3, self.consoleN3)
			self.UpdConLbl(self.EvalResN2, self.consoleN2)
			self.UpdConLbl(self.EvalResN1, self.consoleN1)
			self.UpdConLbl(self.EvalRes, self.console)


		
		elif self.PRG_MODE == MODE.SERVICE:
			row = 3
			col = 3
			for r in range(0, row):
				for c in range(0, col):
					index = int(r*row + c + 1)
					if self.EvalRes[index-1] == ERR.PASSED:
						c_back = "green"	#background colour
					elif self.EvalRes[index-1] == ERR.NOT_BONDED:
						c_back = "blue"		#background colour
					else:
						c_back = "red"
					#switch indices because of maeander index in shuttle
					if (r*row + c + 1) == 4:
						index = 6
					elif (r*row + c + 1) == 6:
						index = 4
					self.console[index-1].configure(text ="Mo%i:\n\tVGate: %2.3f V\n\tVPhase: %2.3f V\n\tVSource: %2.3f V\n\tErrorCode: %i" % (index, self.GateList[index-1], self.PhaseList[index-1], self.SourceList[index-1], self.EvalRes[index-1]))
					self.console[index-1].configure(bg = c_back)

		#--------------Configure tester status------------------------------
		if self.TesterState == STATUS.PASSED:
			c_back = "green"
		else: #self.TesterState == STATUS.ERROR / STATUS.NORES:
			c_back = "red"
		self.tst_status.configure(bg = c_back)
		#--------------Configure tester status------------------------------
		
		#-------------Configure State Info----------------------------------
		self.state_lbl.configure(text = "TESTER STATE:\n %s" % repr(self.State))
		
		#-------------Configure State Info----------------------------------
		
		#--------------Configure Stats--------------------------------------
		self.stat_tot.configure(text = "DUTs TOTAL: \n %i" % self.Ntot)
		self.stat_pass.configure(text ="DUTs PASSED: \n %i" % self.Npass)
		self.stat_fail.configure(text ="DUTs FAILED: \n %i" % self.Nfail)
		self.stat_gsshort.configure(text = "DUTs GS Short: \n %i" % self.Ngs_short)
		self.stat_dsshort.configure(text = "DUTs DS Short: \n %i" % self.Nds_short)
		self.stat_notbonded.configure(text = "DUTs Not Bonded: \n %i" % self.Nnot_bonded)
		#--------------Configure Stats--------------------------------------
	