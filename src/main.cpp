#include <Arduino.h>

#include <TM1637Display.h>

// Definir los pines CLK y DIO para el TM1637
#define CLK 2
#define DIO 3

TM1637Display display(CLK, DIO);

void setup() {
  display.setBrightness(6); // ~80% en rango 0-7 de la libreria TM1637
}

void loop() {
  for (int i = 0; i <= 100; i++) {
    display.showNumberDec(i, false); // Mostrar el número en decimal
    delay(1000);
  }
  delay(2000); // Esperar antes de comenzar la cuenta regresiva
  for (int i = 100; i >= 0; i--) {
    display.showNumberDec(i, false);
    delay(1000);
  }
  delay(2000); // Esperar antes de comenzar el siguiente ciclo
}
