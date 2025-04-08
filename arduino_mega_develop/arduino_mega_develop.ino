/*
  RamanMicroscope V1.0
  Multi-Module Stepper Motor Control with Extended Commands
  ----------------------------------------------------------
  This code now supports:
    1. Multi–motor move command (o…o) where tokens are space–separated.
       Example: "o1A1000 2X2000 4Y-3000o"
       (Unmentioned motors are not updated.)
       Note: Standard Arduino serial buffers are 64 bytes. On an Arduino Mega this may be higher,
             but keep commands within the limits or implement fragmentation if needed.
    2. Get positions command (g…g)
       Example: "g1A 2X 4Yg" returns the target positions.
    3. Check moving command (c…c)
       Example: "c1A 2Xc" returns true/false for each motor (based on if distanceToGo() != 0).
    4. Set positions command (s…s)
       Example: "s1A1000 3Z-500s" sets the motor’s current position without moving.
*/

#include <AccelStepper.h>

AccelStepper stepperA1(AccelStepper::DRIVER, 22, 23);
AccelStepper stepperX1(AccelStepper::DRIVER, 24, 25);
AccelStepper stepperY1(AccelStepper::DRIVER, 26, 27);
AccelStepper stepperZ1(AccelStepper::DRIVER, 28, 29);

AccelStepper stepperA2(AccelStepper::DRIVER, 30, 31);
AccelStepper stepperX2(AccelStepper::DRIVER, 32, 33);
AccelStepper stepperY2(AccelStepper::DRIVER, 34, 35);
AccelStepper stepperZ2(AccelStepper::DRIVER, 36, 37);

AccelStepper stepperA3(AccelStepper::DRIVER, 38, 39);
AccelStepper stepperX3(AccelStepper::DRIVER, 40, 41);
AccelStepper stepperY3(AccelStepper::DRIVER, 42, 43);
AccelStepper stepperZ3(AccelStepper::DRIVER, 44, 45);

AccelStepper stepperA4(AccelStepper::DRIVER, 46, 47);
AccelStepper stepperX4(AccelStepper::DRIVER, 48, 49);
AccelStepper stepperY4(AccelStepper::DRIVER, 50, 51);
AccelStepper stepperZ4(AccelStepper::DRIVER, 52, 53);

const int ldr0pin = A0;      // LDR input pin
const int gShutPin = 9;      // Grating shutter pin

const int homingLimitPin = 13; // Or whatever pin you use



// Global array pointer for easier access:
AccelStepper* steppers[] = {
  &stepperA1, &stepperX1, &stepperY1, &stepperZ1,
  &stepperA2, &stepperX2, &stepperY2, &stepperZ2,
  &stepperA3, &stepperX3, &stepperY3, &stepperZ3,
  &stepperA4, &stepperX4, &stepperY4, &stepperZ4
};

// Backoff steps per motor (same order as steppers[])
int backoffSteps[] = {
  300, 5000, 3000, 6000,  // module 1
  300, 300, 300, 300,  // module 2
  3000, 3000, 3000, 3000,  // module 3
  300, 300, 100, 300   // module 4 — Y motor has smaller range
};

// Backoff steps per motor (same order as steppers[])
int homeFastSpeed[] = {
  300, 5000, 2000, 5000,  // module 1
  1000, 1000, 1000, 1000,  // module 2
  1000, 1000, 1000, 1000,  // module 3
  300, 300, 300, 300   // module 4 — Y motor has smaller range
};



void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 16; i++) {
    steppers[i]->setMaxSpeed(5000);
    steppers[i]->setAcceleration(5000);
  }
  
  // custom speeds
  // stepperA1.setMaxSpeed(1000);
  // stepperA1.setAcceleration(1000);

  stepperY4.setMaxSpeed(10000);
  stepperY4.setAcceleration(10000);
  stepperX4.setMaxSpeed(300);
  stepperX4.setAcceleration(1000);
  // stepperX1.setMaxSpeed(10000);
  // stepperX1.setAcceleration(5000);

  pinMode(gShutPin, OUTPUT);
  digitalWrite(gShutPin, LOW);
  pinMode(homingLimitPin, INPUT_PULLUP); // Assuming active-low switch

  Serial.print("Arduino controller ready to receive commands");
  Serial.println("#CF");
}

void loop() {
  // Run all motors continuously for smooth simultaneous movement.
  for (int i = 0; i < 16; i++) {
    steppers[i]->run();
  }
  
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    parseCommand(command);
    // Acknowledge receipt of command (could be adjusted per command type)
    Serial.println("#CF");
  }
}

// --- Hardware specific functions ---
void ramanMode() {
  stepperA1.move(6000);
  Serial.println("Moving to Raman Mode...");
}

void imageMode() {
  stepperA1.move(-6000);
  Serial.println("Moving to Image Mode...");
}

void monoShutter(String state) {
  if (state == "off") {
    digitalWrite(gShutPin, LOW);
    Serial.println("Shutter closed.");
  } else if (state == "on") {
    digitalWrite(gShutPin, HIGH);
    Serial.println("Shutter open.");
  }
}

void readLDR() {
  int count = 0;
  long ldr0value = 0;
  while (count < 10) {
    ldr0value += analogRead(ldr0pin);
    count++;
  }
  Serial.print('t');
  Serial.println(ldr0value);
}

void homeMotor(char module, char motor) {
  int idx = getStepperIndex(module, motor);
  if (idx < 0 || idx >= 16) {
    Serial.println("Invalid motor.");
    return;
  }

  AccelStepper* m = steppers[idx];

  // Save original settings
  float originalMaxSpeed = m->maxSpeed();
  float originalAcceleration = m->acceleration();

  // Homing parameters
  int fastSpeed = homeFastSpeed[idx];
  const int slowSpeed = 300;
  const unsigned long timeoutMs = 60000; // 1 min timeout
  int backoff = backoffSteps[idx];

  unsigned long tStart;

  // Fast approach
  m->setMaxSpeed(fastSpeed);
  m->setAcceleration(fastSpeed);
  m->move(-150000);

  tStart = millis();
  while (digitalRead(homingLimitPin) == HIGH) {
    if (millis() - tStart > timeoutMs) {
      Serial.println("Timeout during fast approach.");
      goto restore;
    }
    m->run();
  }

  m->stop();
  while (m->isRunning()) m->run();

  // Back off
  m->move(backoff);
  while (m->distanceToGo() != 0) m->run();

  // Slow approach
  m->setMaxSpeed(slowSpeed);
  m->setAcceleration(slowSpeed);
  m->move(-100000);

  tStart = millis();
  while (digitalRead(homingLimitPin) == HIGH) {
    if (millis() - tStart > timeoutMs) {
      Serial.println("Timeout during slow re-approach.");
      goto restore;
    }
    m->run();
  }

  m->stop();
  while (m->isRunning()) m->run();

restore:
  // Restore original settings
  m->setMaxSpeed(originalMaxSpeed);
  m->setAcceleration(originalAcceleration);

  long pos = m->currentPosition();
  Serial.print("Homed motor ");
  Serial.print(module);
  Serial.print(motor);
  Serial.print(" at position ");
  Serial.println(pos);
  // m->move(1000); // to move off limit switch
}


// --- Command parsing helper ---
/*
  token format for motion commands:
    token: <module><motor><position>
      e.g., "1A1000" means module 1, motor A to position 1000.
    module: '1'..'4'
    motor: A, X, Y, Z
  
  The index into the steppers array is calculated as:
    index = (module - '1') * 4 + motorOffset,
  where motorOffset is:
    0 for A, 1 for X, 2 for Y, 3 for Z.
*/
int getStepperIndex(char module, char motor) {
  int moduleIndex = module - '1';
  int motorOffset = 0;
  switch (motor) {
    case 'A': motorOffset = 0; break;
    case 'X': motorOffset = 1; break;
    case 'Y': motorOffset = 2; break;
    case 'Z': motorOffset = 3; break;
    default: break;
  }
  return moduleIndex * 4 + motorOffset;
}

// --- Multi-token command parsers ---

// Multi-move command: e.g., o1A1000 2X2000 4Y-3000o
void parseMultiMoveCommand(String cmdContent) {
  int start = 0;
  cmdContent.trim();
  while (start < cmdContent.length()) {
    int spaceIndex = cmdContent.indexOf(' ', start);
    String token;
    if (spaceIndex == -1) { // last token
      token = cmdContent.substring(start);
      start = cmdContent.length();
    } else {
      token = cmdContent.substring(start, spaceIndex);
      start = spaceIndex + 1;
    }
    token.trim();
    if (token.length() < 3) continue;  // invalid token
    char module = token.charAt(0);
    char motor  = token.charAt(1);
    long pos = token.substring(2).toInt();  // works up to ±2,147,483,647
    int idx = getStepperIndex(module, motor);
    if (idx >= 0 && idx < 16) {
      steppers[idx]->move(pos);
      Serial.print("Moving motor ");
      Serial.print(module);
      Serial.print(motor);
      Serial.println(pos);
    }
  }
}

// Get positions command: e.g., g1A 2X 4Yg
// Responds with a token and current target position.
void getPositions(String cmdContent) {
  int start = 0;
  cmdContent.trim();
  while (start < cmdContent.length()) {
    int spaceIndex = cmdContent.indexOf(' ', start);
    String token;
    if (spaceIndex == -1) {
      token = cmdContent.substring(start);
      start = cmdContent.length();
    } else {
      token = cmdContent.substring(start, spaceIndex);
      start = spaceIndex + 1;
    }
    token.trim();
    if (token.length() < 2) continue;  // invalid token
    char module = token.charAt(0);
    char motor = token.charAt(1);
    int idx = getStepperIndex(module, motor);
    if (idx >= 0 && idx < 16) {
      long pos = steppers[idx]->targetPosition();
      Serial.print(module);
      Serial.print(motor);
      Serial.print(":");
      Serial.print(pos);
      Serial.print(" ");
    }
  }
  Serial.println();
}

// Check moving command: e.g., c1A 2Xc
// For each token, if the motor’s distanceToGo() != 0, it is moving.
void checkMoving(String cmdContent) {
  int start = 0;
  cmdContent.trim();
  while (start < cmdContent.length()) {
    int spaceIndex = cmdContent.indexOf(' ', start);
    String token;
    if (spaceIndex == -1) {
      token = cmdContent.substring(start);
      start = cmdContent.length();
    } else {
      token = cmdContent.substring(start, spaceIndex);
      start = spaceIndex + 1;
    }
    token.trim();
    if (token.length() < 2) continue;
    char module = token.charAt(0);
    char motor = token.charAt(1);
    int idx = getStepperIndex(module, motor);
    if (idx >= 0 && idx < 16) {
      bool moving = (steppers[idx]->distanceToGo() != 0);
      Serial.print(module);
      Serial.print(motor);
      Serial.print(":");
      Serial.print(moving ? "true" : "false");
      Serial.print(" ");
    }
  }
  Serial.println();
}

// Set positions command: e.g., s1A1000 3Z-500s
// This overwrites the current position using setCurrentPosition.
void setPositions(String cmdContent) {
  int start = 0;
  cmdContent.trim();
  while (start < cmdContent.length()) {
    int spaceIndex = cmdContent.indexOf(' ', start);
    String token;
    if (spaceIndex == -1) {
      token = cmdContent.substring(start);
      start = cmdContent.length();
    } else {
      token = cmdContent.substring(start, spaceIndex);
      start = spaceIndex + 1;
    }
    token.trim();
    if (token.length() < 3) continue;
    char module = token.charAt(0);
    char motor = token.charAt(1);
    int pos = token.substring(2).toInt();
    int idx = getStepperIndex(module, motor);
    if (idx >= 0 && idx < 16) {
      steppers[idx]->setCurrentPosition(pos);
      Serial.print("Set motor ");
      Serial.print(module);
      Serial.print(motor);
      Serial.print(" position to ");
      Serial.println(pos);
    }
  }
}

// --- Main command parser ---
void parseCommand(String command) {
  command.trim();
  // Multi-motor move command: o...o
  if (command.startsWith("o") && command.endsWith("o")) {
    String content = command.substring(1, command.length() - 1);
    parseMultiMoveCommand(content);
  }
  // Get positions command: g...g
  else if (command.startsWith("g") && command.endsWith("g")) {
    String content = command.substring(1, command.length() - 1);
    getPositions(content);
  }
  // Check moving command: c...c
  else if (command.startsWith("c") && command.endsWith("c")) {
    String content = command.substring(1, command.length() - 1);
    checkMoving(content);
  }
  // Set positions command: s...s
  else if (command.startsWith("s") && command.endsWith("s")) {
    String content = command.substring(1, command.length() - 1);
    setPositions(content);
  }
  // Hardware specific commands in m...m envelope.
  else if (command.startsWith("m") && command.endsWith("m")) {
    String content = command.substring(1, command.length() - 1);
    // assume command and value are separated by a space at position 3 (e.g., "gsh on")
    String com = content.substring(0, 3);
    String comvalstring = content.substring(4);
    if (com == "gsh") {
      monoShutter(comvalstring);
    } else if (com == "ld0") {
      readLDR();
    } else {
      Serial.println("Unknown hardware command.");
    }
  }
  // Home a motor: e.g., h1A
  else if (command.startsWith("h") && command.length() == 3) {
    char module = command.charAt(1);
    char motor = command.charAt(2);
    homeMotor(module, motor);
  }

  // Legacy mode commands
  else if (command == "imagemode") {
    imageMode();
  }
  else if (command == "ramanmode") {
    ramanMode();
  }
  else {
    Serial.println("Unrecognized command format.");
  }
}
