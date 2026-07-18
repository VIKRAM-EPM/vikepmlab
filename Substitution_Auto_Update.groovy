// This script is developed by Vikram Kumar
// Version 3.0
// This script is scheduled to run every week on Sunday
// Purpose of this script - Change Substitution variable every week according to Fiscal Calender (5-4-4)
//            - Also populate WK1_R to WK14_R with clean period names (no year suffix)
//            - Send simple plain text email via EPM Automate
//
// Naming convention: prefix indicates rolling granularity, _R suffix = clean (no year) version
//   D1-D30   = rolling days
//   WK1-WK14 = rolling weeks (this script, ~90 days / 1 quarter)
//   M1-M13   = rolling months

import java.util.Calendar
import oracle.epm.api.model.Application


// =====================================================================
// *** ANNUAL UPDATE SECTION ONLY CHANGE THIS BLOCK EACH NEW FY ***
// =====================================================================
//
// CURRENT FY the new fiscal year your team just provided
// PRIOR FY  whatever was "current" in the previous run of this script
//
// Pattern key : 52-week year = [5,4,4, 5,4,4, 5,4,4, 5,4,4]
//        53-week year = [5,4,4, 5,4,4, 5,4,4, 5,4,5] P12 gets extra week
// =====================================================================

// -- CURRENT FY config --------------------------------------------------
def CFG_FY_YEAR  = 2025   // Calendar year of FY start date
def CFG_FY_MONTH  = 11    // Month (0=Jan, 1=Feb ... 11=Dec)
def CFG_FY_DAY   = 29    // Day  Dec 29, 2025 = FY2026 start
def CFG_FY_LABEL  = "2026"  // Label printed in variable values
def CFG_FY_PATTERN = [5,4,4, 5,4,4, 5,4,4, 5,4,5] // 53-week year

// -- PRIOR FY config (previous year needed for year-end transition) ---
def CFG_PRIOR_YEAR  = 2024  // Calendar year of prior FY start date
def CFG_PRIOR_MONTH  = 11   // Month Dec
def CFG_PRIOR_DAY   = 30   // Day  Dec 30, 2024 = FY2025 start
def CFG_PRIOR_LABEL  = "2025" // Label for prior FY values
def CFG_PRIOR_PATTERN = [5,4,4, 5,4,4, 5,4,4, 5,4,5] // 53-week year

// =====================================================================
// *** EMAIL CONFIG  !! FILL IN THESE 4 VALUES BEFORE RUNNING !!  ***
// =====================================================================
def EMAIL_TO    = "<youremailid>"    // Recipient email
def EMAIL_USER   = "<ServiceAccount>"//  Service account username
def EMAIL_PASSWORD = '<Password>'       //  Make sure in single quotes if using plain password, that is another bug kind of
def EMAIL_URL   = "<Oracle EPM Service URL>"  // 
// =====================================================================
// *** END OF ANNUAL UPDATE DO NOT CHANGE ANYTHING BELOW THIS LINE ***
// =====================================================================


// TEST DATE
// For testing: uncomment the set() line and enter a date
// For production: leave only Calendar.getInstance() uncommented
def today = Calendar.getInstance()
// today.set(2026, 4, 11) // e.g. May 11 2026 (Jan=0 ... Dec=11)


// BUILD CALENDAR OBJECTS FROM CONFIG
def fiscalStart = Calendar.getInstance()
fiscalStart.set(CFG_FY_YEAR, CFG_FY_MONTH, CFG_FY_DAY)

def priorStart = Calendar.getInstance()
priorStart.set(CFG_PRIOR_YEAR, CFG_PRIOR_MONTH, CFG_PRIOR_DAY)


// SAFE DAYS-BETWEEN (no getTime Oracle SDK compatible)
def getDaysBetween = { Calendar start, Calendar end ->
  def temp = (Calendar) start.clone()
  int days = 0
  while (temp.before(end)) {
    temp.add(Calendar.DATE, 1)
    days++
  }
  return days
}


// FISCAL PERIOD + WEEK MAPPER
// Automatically picks current or prior FY based on the calc date.
// Uses the full 12-period pattern directly (no modulo shortcut).
def getFiscal = { Calendar cal ->

  Calendar anchor
  String  label
  List   pat

  if (!cal.before(fiscalStart)) {
    anchor = fiscalStart
    label = CFG_FY_LABEL
    pat  = CFG_FY_PATTERN
  } else {
    anchor = priorStart
    label = CFG_PRIOR_LABEL
    pat  = CFG_PRIOR_PATTERN
  }

  def totalDays   = getDaysBetween(anchor, cal)
  def totalWeeks   = (totalDays.intdiv(7)) + 1
  def remainingWeeks = totalWeeks - 1
  def fm       = 1

  while (true) {
    if (fm > 12) fm = 12
    def weeksInPeriod = pat[fm - 1]
    if (fm == 12) {
      return ["P12", remainingWeeks + 1, label]
    }
    if (remainingWeeks < weeksInPeriod) {
      return ["P" + String.format("%02d", fm), remainingWeeks + 1, label]
    }
    remainingWeeks -= weeksInPeriod
    fm++
  }
}


// WK14 = LAST COMPLETED WEEK
def baseDate = (Calendar) today.clone()
baseDate.add(Calendar.DATE, -7)


/*
  BUILD newValues AND cleanValues IN SAME LOOP
  newValues  stores full value e.g. P02_WK1-2026
  cleanValues stores clean value e.g. P02_WK1
  Both built at same time from same getFiscal() result
  to avoid null reference issues
*/
def newValues  = [:]
def cleanValues = [:]

for (int i = 14; i >= 1; i--) {
  def calcDate = (Calendar) baseDate.clone()
  calcDate.add(Calendar.DATE, -7 * (14 - i))
  def res = getFiscal(calcDate)

  String fullValue = "${res[0]}_WK${res[1]}-${res[2]}"
  String cleanValue = "${res[0]}_WK${res[1]}"

  newValues["WK${i}"]   = fullValue
  cleanValues["WK${i}_R"] = cleanValue
}


// READ CURRENT (PREVIOUS) VALUES VIA EPM API
Application app = operation.application
// Cube cube = app.getCube(CUBE_NAME)

def previousValues = [:]

(1..14).each { i ->
  String varName = "WK${i}"
  String current = app.getSubstitutionVariableValue(varName)
  previousValues[varName] = current ?: "(not set)"
}


// BUILD RUN DATE STRING
String runDate = "${today.get(Calendar.YEAR)}-" +
    "${String.format('%02d', today.get(Calendar.MONTH) + 1)}-" +
    "${String.format('%02d', today.get(Calendar.DAY_OF_MONTH))}"


// SIMPLIFIED log()  prints to job console only
def log = { String line ->
  println line
}


// PRINT HEADER
log("")
log("=".multiply(72))
log(" Substitution Variable Update - 5-4-4 Fiscal Calendar")
log(" App   : ${app.getName()}")
log(" Run Date: ${runDate}")
log("=".multiply(72))


// WK1 TO WK14 TABLE
log("")
log(" [ WK1 to WK14 - with Year Suffix ]")
log(String.format(" %-10s %-22s %-22s %s",
    "Variable", "Previous Value", "New Value", "Changed?"))
log(" " + "-".multiply(67))

(1..14).each { i ->
  String varName = "WK${i}"
  String oldVal = previousValues[varName]
  String newVal = newValues[varName]
  String changed = (oldVal != newVal) ? "YES" : "no"
  log(String.format(" %-10s %-22s %-22s %s",
      varName, oldVal, newVal, changed))
}

log(" " + "-".multiply(67))


// WK1_R TO WK14_R TABLE
log("")
log(" [ WK1_R to WK14_R - Clean Period Names (no year suffix) ]")
log(String.format(" %-10s %-22s %-22s %s",
    "Variable", "Previous Value", "New Value", "Changed?"))
log(" " + "-".multiply(67))

(1..14).each { i ->
  String varName = "WK${i}_R"
  String oldVal = app.getSubstitutionVariableValue(varName) ?: "(not set)"
  String newVal = cleanValues[varName]
  String changed = (oldVal != newVal) ? "YES" : "no"
  log(String.format(" %-10s %-22s %-22s %s",
      varName, oldVal, newVal, changed))
}

log(" " + "-".multiply(67))
log("")


// SET NEW VALUES
int updatedCount = 0
int skippedCount = 0

// SET WK1 TO WK14
(1..14).each { i ->
  String varName = "WK${i}"
  String oldVal = previousValues[varName]
  String newVal = newValues[varName]

  if (oldVal != newVal) {
    app.setSubstitutionVariableValue(varName, newVal)
    updatedCount++
  } else {
    skippedCount++
  }
}

// SET WK1_R TO WK14_R
(1..14).each { i ->
  String varName = "WK${i}_R"
  String oldVal = app.getSubstitutionVariableValue(varName) ?: "(not set)"
  String newVal = cleanValues[varName]

  if (oldVal != newVal) {
    app.setSubstitutionVariableValue(varName, newVal)
    updatedCount++
  } else {
    skippedCount++
  }
}


// SUMMARY
log(" Result : ${updatedCount} variable(s) updated, ${skippedCount} skipped (already current)")
log("")
log("=".multiply(72))
log(" Script completed successfully.")
log("=".multiply(72))


// SEND EMAIL VIA EPM AUTOMATE
try {
  String subject  = "Test Env Substitution Variables are updated successfully"
  String emailBody = "Test Environment Substitution Variables are updated from WK1 to WK14"

  EpmAutomate automate = getEpmAutomate()

  // Step 1  Encrypt password
  EpmAutomateStatus encryptStatus = automate.execute(
    'encrypt', EMAIL_PASSWORD, 'oracleKey', 'password.epw'
  )
  println "Encrypt : ${encryptStatus.getStatus()}"
  println encryptStatus.getOutput()

  // Step 2  Login
  EpmAutomateStatus loginStatus = automate.execute(
    'login', EMAIL_USER, 'password.epw', EMAIL_URL
  )
  println "Login  : ${loginStatus.getStatus()}"
  println loginStatus.getOutput()

  // Step 3  Send Mail
  EpmAutomateStatus mailStatus = automate.execute(
    'sendmail',
    EMAIL_TO,
    subject,
    "Body=${emailBody}"
  )
  println "SendMail: ${mailStatus.getStatus()}"
  println mailStatus.getOutput()

  // Step 4  Logout
  EpmAutomateStatus logoutStatus = automate.execute('logout')
  println "Logout : ${logoutStatus.getStatus()}"
  println "Email sent successfully to: ${EMAIL_TO}"

} catch (Exception e) {
  println "WARNING: Email sending failed - ${e.getMessage()}"
}