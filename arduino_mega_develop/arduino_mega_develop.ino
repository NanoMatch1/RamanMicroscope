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

const int stepPinA1 = 22;
const int dirPinA1 = 23;
const int stepPinX1 = 24;
const int dirPinX1 = 25;
const int stepPinY1 = 26;
const int dirPinY1 = 27;
const int stepPinZ1 = 28;
const int dirPinZ1 = 29;

const int stepPinA2 = 30;
const int dirPinA2 = 31;
const int stepPinX2 = 32;
const int dirPinX2 = 33;
const int stepPinY2 = 34;
const int dirPinY2 = 35;
const int stepPinZ2 = 36;
const int dirPinZ2 = 37;

const int stepPinA3 = 38;
const int dirPinA3 = 39;
const int stepPinX3 = 40;
const int dirPinX3 = 41;
const int stepPinY3 = 42;
const int dirPinY3 = 43;
const int stepPinZ3 = 44;
const int dirPinZ3 = 45;

const int stepPinA4 = 46;
const int dirPinA4 = 47;
const int stepPinX4 = 48;
const int dirPinX4 = 49;
const int stepPinY4 = 50;
const int dirPinY4 = 51;
const int stepPinZ4 = 52;
const int dirPinZ4 = 53;

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
const int ledPin = 11;       // LED illunimation pin

const int homingLimitPin = 13; // Or whatever pin you use



// Global array pointer for easier access:
AccelStepper* steppers[] = {
  &stepperA1, &stepperX1, &stepperY1, &stepperZ1,
  &stepperA2, &stepperX2, &stepperY2, &stepperZ2,
  &stepperA3, &stepperX3, &stepperY3, &stepperZ3,
  &stepperA4, &stepperX4, &stepperY4, &stepperZ4
};

// Homing backoff steps per motor (same order as steppers[])
int backoffSteps[] = {
  300, 5000, 500, 6000,  // module 1
  300, 300, 300, 300,  // module 2
  500, 500, 500, 500,  // module 3
  300, 300, 100, 300   // module 4 — Y motor has smaller range
};

// Homing fast speed per motor (same order as steppers[])
int homeFastSpeed[] = {
  300, 2500, 500, 2500,  // module 1
  1000, 1000, 1000, 1000,  // module 2
  250, 250, 250, 250,  // module 3
  300, 300, 300, 300   // module 4 — Y motor has smaller range
};

// homing slow speed per motor (same order as steppers[])
int homeSlowSpeed[] = {
  300, 250, 100, 300,  // module 1
  300, 300, 300, 300,  // module 2
  50, 50, 50, 50,  // module 3
  300, 300, 300, 300   // module 4 — Y motor has smaller range
};

void setup() {
  Serial.begin(9600);

  delay(50);
  
  pinMode(stepPinA1, INPUT);
  pinMode(stepPinX1, INPUT);
  pinMode(stepPinY1, INPUT);
  pinMode(stepPinZ1, INPUT);
  pinMode(dirPinA1, INPUT);
  pinMode(dirPinX1, INPUT);
  pinMode(dirPinY1, INPUT);
  pinMode(dirPinZ1, INPUT);

  pinMode(stepPinA2, INPUT);
  pinMode(stepPinX2, INPUT);
  pinMode(stepPinY2, INPUT);
  pinMode(stepPinZ2, INPUT);
  pinMode(dirPinA2, INPUT);
  pinMode(dirPinX2, INPUT);
  pinMode(dirPinY2, INPUT);
  pinMode(dirPinZ2, INPUT);

  pinMode(stepPinA3, INPUT);
  pinMode(stepPinX3, INPUT);
  pinMode(stepPinY3, INPUT);
  pinMode(stepPinZ3, INPUT);
  pinMode(dirPinA3, INPUT);
  pinMode(dirPinX3, INPUT);
  pinMode(dirPinY3, INPUT);
  pinMode(dirPinZ3, INPUT);

  pinMode(stepPinA4, INPUT);
  pinMode(stepPinX4, INPUT);
  pinMode(stepPinY4, INPUT);
  pinMode(stepPinZ4, INPUT);
  pinMode(dirPinA4, INPUT);
  pinMode(dirPinX4, INPUT);
  pinMode(dirPinY4, INPUT);
  pinMode(dirPinZ4, INPUT);
  
  

  for (int i = 0; i < 16; i++) {
    steppers[i]->setMaxSpeed(5000);
    steppers[i]->setAcceleration(5000);
  }
  
  // custom speeds
  // stepperA1.setMaxSpeed(1000);
  // stepperA1.setAcceleration(1000);

  stepperX4.setMaxSpeed(300);
  stepperX4.setAcceleration(300);
  stepperY4.setMaxSpeed(300);
  stepperY4.setAcceleration(300);
  stepperZ4.setMaxSpeed(300);
  stepperZ4.setAcceleration(300);
  stepperA4.setMaxSpeed(300);
  stepperA4.setAcceleration(300);
  stepperY1.setMaxSpeed(1500);
  stepperY1.setAcceleration(1000);
  stepperX1.setMaxSpeed(3000);
  stepperX1.setAcceleration(3000);

  pinMode(gShutPin, OUTPUT);
  digitalWrite(gShutPin, LOW);
  pinMode(homingLimitPin, INPUT_PULLUP); // Assuming active-low switch

  delay(500);

  pinMode(stepPinA1, OUTPUT);
  pinMode(stepPinX1, OUTPUT);
  pinMode(stepPinY1, OUTPUT);
  pinMode(stepPinZ1, OUTPUT);
  pinMode(dirPinA1, OUTPUT);
  pinMode(dirPinX1, OUTPUT);
  pinMode(dirPinY1, OUTPUT);
  pinMode(dirPinZ1, OUTPUT);

  pinMode(stepPinA2, OUTPUT);
  pinMode(stepPinX2, OUTPUT);
  pinMode(stepPinY2, OUTPUT);
  pinMode(stepPinZ2, OUTPUT);
  pinMode(dirPinA2, OUTPUT);
  pinMode(dirPinX2, OUTPUT);
  pinMode(dirPinY2, OUTPUT);
  pinMode(dirPinZ2, OUTPUT);

  pinMode(stepPinA3, OUTPUT);
  pinMode(stepPinX3, OUTPUT);
  pinMode(stepPinY3, OUTPUT);
  pinMode(stepPinZ3, OUTPUT);
  pinMode(dirPinA3, OUTPUT);
  pinMode(dirPinX3, OUTPUT);
  pinMode(dirPinY3, OUTPUT);
  pinMode(dirPinZ3, OUTPUT);

  pinMode(stepPinA4, OUTPUT);
  pinMode(stepPinX4, OUTPUT);
  pinMode(stepPinY4, OUTPUT);
  pinMode(stepPinZ4, OUTPUT);
  pinMode(dirPinA4, OUTPUT);
  pinMode(dirPinX4, OUTPUT);
  pinMode(dirPinY4, OUTPUT);
  pinMode(dirPinZ4, OUTPUT);

  delay(50);

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
  stepperA2.move(6000);
  Serial.println("Moving to Raman Mode...");
}

void imageMode() {
  stepperA2.move(-6000);
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

void toggleIllumination(String state) {
  if (state == "off") {
    digitalWrite(ledPin, LOW);
    Serial.println("LED off");
  }
  else if (state == "on") {
    digitalWrite(ledPin, HIGH);
    Serial.println("LED on");
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
  int slowSpeed = homeSlowSpeed[idx];
  int backoff = backoffSteps[idx];
  const unsigned long timeoutMs = 120000; // 2 min timeout

  unsigned long tStart;

  // Fast approach
  m->setMaxSpeed(fastSpeed);
  // m->setAcceleration(fastSpeed);
  m->move(-200000);

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
  m->setAcceleration(10000);
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
    long pos = token.substring(2).toInt();
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
    } else if (com == "led") {
      toggleIllumination(comvalstring);
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
