#include <Arduino.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// LCD 20x4 con backpack PCF8574T (direccion tipica 0x27)
LiquidCrystal_I2C lcd(0x27, 20, 4);

int counterValue = 0;
unsigned long lastTickMs = 0;
const unsigned long intervalMs = 350;

void setup() {
  lcd.init();
  lcd.backlight();

  lcd.setCursor(0, 0);
  lcd.print("Contador 0-100");
  lcd.setCursor(0, 1);
  lcd.print("Iniciando...");
  delay(1200);
  lcd.clear();
}

void loop() {
  unsigned long now = millis();
  if (now - lastTickMs >= intervalMs) {
    lastTickMs = now;

    lcd.setCursor(0, 0);
    lcd.print("Cuenta:            ");
    lcd.setCursor(8, 0);
    lcd.print(counterValue);

    lcd.setCursor(0, 1);
    lcd.print("LCD 20x4 I2C OK    ");

    counterValue++;
    if (counterValue > 100) {
      counterValue = 0;
    }
  }
}
