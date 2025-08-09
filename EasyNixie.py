"""
CircuitPython driver for EasyNixie IN-12A Nixie tube modules
Compatible with ESP32-S3, Raspberry Pi Pico W, and other CircuitPython boards

Author: CircuitPython Implementation
Based on: EasyNixie Arduino library concepts
"""

import board
import digitalio
import time
import pwmio
from micropython import const
import random

# Color constants (matching Arduino library EXACTLY)
EASY_NIXIE_BLUE = 1
EASY_NIXIE_GREEN = 2  
EASY_NIXIE_RED = 3
EASY_NIXIE_WHITE = 4
EASY_NIXIE_RuB = 5  # Red + Blue
EASY_NIXIE_RuG = 6  # Red + Green  
EASY_NIXIE_BuG = 7  # Blue + Green

class EasyNixie:
    def __init__(self, out_en_pin, shcp_pin, stcp_pin, dsin_pin, num_tubes=1):
        """
        Initialize EasyNixie driver matching Arduino constructor with multi-tube support
        
        Args:
            out_en_pin: Output enable pin (OUT_EN on EasyNixie)
            shcp_pin: Shift clock pin (SHCP)
            stcp_pin: Storage clock pin (STCP) 
            dsin_pin: Data serial input pin (DSIN)
            num_tubes: Number of daisy-chained modules (default: 1)
        """
        self.num_tubes = num_tubes
        self.display_buffer = [(10, EASY_NIXIE_WHITE, True, False, 0)] * num_tubes  # (digit, color, voltage, comma, dimming)
        
        # Initialize control pins exactly like Arduino
        self.shcp = digitalio.DigitalInOut(shcp_pin)
        self.shcp.direction = digitalio.Direction.OUTPUT
        self.shcp.value = False
        
        self.stcp = digitalio.DigitalInOut(stcp_pin)
        self.stcp.direction = digitalio.Direction.OUTPUT
        self.stcp.value = False
        
        self.dsin = digitalio.DigitalInOut(dsin_pin)
        self.dsin.direction = digitalio.Direction.OUTPUT
        self.dsin.value = False
        
        # Set up PWM on OUT_EN for dimming
        try:
            self.out_en_pwm = pwmio.PWMOut(out_en_pin, frequency=1000, duty_cycle=65535)
            self.dimming_available = True
            print("PWM dimming successfully initialized on OUT_EN pin")
        except Exception as e:
            print(f"PWM setup failed: {e}")
            # Fall back to digital control
            self.out_en = digitalio.DigitalInOut(out_en_pin)
            self.out_en.direction = digitalio.Direction.OUTPUT
            self.out_en.value = True
            self.dimming_available = False
            print("Falling back to digital OUT_EN control (always on)")
    
    def slow_shift_out(self, data_byte):
        """
        Shift out a byte MSB first, exactly matching Arduino slowShiftOut
        """
        for i in range(8):
            bit_pos = 7 - i
            bit_value = bool(data_byte & (1 << bit_pos))
            self.dsin.value = bit_value
            time.sleep(0.000001)
            self.shcp.value = True
            time.sleep(0.000001)
            self.shcp.value = False
            time.sleep(0.000001)
    
    def latch(self):
        """
        Latch function matching Arduino - LOW, delay, HIGH (no return to LOW!)
        """
        self.stcp.value = False
        time.sleep(0.001)
        self.stcp.value = True
    
    def set_nixie(self, number, color=EASY_NIXIE_WHITE, voltage=True, comma=False, dimming=255):
        """
        Set nixie display, matching Arduino SetNixie function exactly
        This ONLY shifts data, doesn't latch - call latch() separately!
        
        Args:
            number: Digit to display (0-9, or 10+ for blank)
            color: LED color (use EASY_NIXIE_* constants)
            voltage: High voltage enable (default True like Arduino)
            comma: Comma/decimal point
            dimming: PWM dimming (0=off, 255=brightest)
        """
        # Handle PWM dimming on OUT_EN pin (like Arduino analogWrite)
        # Arduino analogWrite: higher value = higher duty cycle = brighter
        if self.dimming_available:
            duty_cycle = int((dimming / 255.0) * 65535)
            self.out_en_pwm.duty_cycle = duty_cycle
            print(f"Set dimming: {dimming} -> duty_cycle: {duty_cycle}")
        elif dimming > 0:
            print(f"Warning: Dimming requested ({dimming}) but PWM not available")
        
        # Build second shift register data (control bits)
        second_shift_register_data = 0b00011100
        
        if number == 8:
            second_shift_register_data |= 0b00000001
        if number == 9:
            second_shift_register_data |= 0b00000010
        
        if color == EASY_NIXIE_RED:
            second_shift_register_data &= 0b11101111
        if color == EASY_NIXIE_GREEN:
            second_shift_register_data &= 0b11110111
        if color == EASY_NIXIE_BLUE:
            second_shift_register_data &= 0b11111011
        if color == EASY_NIXIE_WHITE:
            second_shift_register_data &= 0b11100011
        if color == EASY_NIXIE_RuB:
            second_shift_register_data &= 0b11101011
        if color == EASY_NIXIE_RuG:
            second_shift_register_data &= 0b11100111
        if color == EASY_NIXIE_BuG:
            second_shift_register_data &= 0b11110011
        
        if voltage:
            second_shift_register_data |= 0b00100000
        if comma:
            second_shift_register_data |= 0b01000000
        
        self.slow_shift_out(second_shift_register_data)
        
        if number < 8:
            first_shift_register_data = 1 << number
        else:
            first_shift_register_data = 0
        
        self.slow_shift_out(first_shift_register_data)
    
    def set_tube(self, tube_index, number, color=EASY_NIXIE_WHITE, voltage=True, comma=False, dimming=255):
        """
        Set a specific tube in multi-tube setup
        
        Args:
            tube_index: Which tube (0 to num_tubes-1, 0 is rightmost)
            number: Digit to display (0-9, or 10+ for blank)
            color: LED color
            voltage: High voltage enable
            comma: Comma/decimal point  
            dimming: Brightness (0=off, 255=brightest)
        """
        if 0 <= tube_index < self.num_tubes:
            self.display_buffer[tube_index] = (number, color, voltage, comma, dimming)
    
    def update_display(self):
        """
        Update all tubes with buffered data
        Sends data to all tubes then latches simultaneously
        """
        # Send data for all tubes (rightmost tube first for daisy chain)
        for i in range(self.num_tubes - 1, -1, -1):
            number, color, voltage, comma, dimming = self.display_buffer[i]
            
            # Set the dimming for this update (affects all tubes)
            if self.dimming_available:
                duty_cycle = int((dimming / 255.0) * 65535)
                self.out_en_pwm.duty_cycle = duty_cycle
            
            # Build and send data for this tube
            self._send_tube_data(number, color, voltage, comma)
        
        # Latch all data to outputs simultaneously
        self.latch()
    
    def _send_tube_data(self, number, color, voltage, comma):
        """Send data for a single tube (internal helper)"""
        # Build second shift register data (control bits)
        second_shift_register_data = 0b00011100
        
        if number == 8:
            second_shift_register_data |= 0b00000001
        if number == 9:
            second_shift_register_data |= 0b00000010
        
        if color == EASY_NIXIE_RED:
            second_shift_register_data &= 0b11101111
        if color == EASY_NIXIE_GREEN:
            second_shift_register_data &= 0b11110111
        if color == EASY_NIXIE_BLUE:
            second_shift_register_data &= 0b11111011
        if color == EASY_NIXIE_WHITE:
            second_shift_register_data &= 0b11100011
        if color == EASY_NIXIE_RuB:
            second_shift_register_data &= 0b11101011
        if color == EASY_NIXIE_RuG:
            second_shift_register_data &= 0b11100111
        if color == EASY_NIXIE_BuG:
            second_shift_register_data &= 0b11110011
        
        if voltage:
            second_shift_register_data |= 0b00100000
        if comma:
            second_shift_register_data |= 0b01000000
        
        self.slow_shift_out(second_shift_register_data)
        
        if number < 8:
            first_shift_register_data = 1 << number
        else:
            first_shift_register_data = 0
        
        self.slow_shift_out(first_shift_register_data)
    
    def set_number(self, number, color=EASY_NIXIE_WHITE, leading_zeros=False, dimming=255):
        """
        Display a number across multiple tubes
        
        Args:
            number: Integer number to display
            color: LED color for all digits
            leading_zeros: If True, show leading zeros
            dimming: Brightness (0=off, 255=brightest)
        """
        # Convert number to string
        if number < 0:
            num_str = str(abs(number))
        else:
            num_str = str(number)
        
        # Clear display buffer
        for i in range(self.num_tubes):
            self.display_buffer[i] = (10, color, True, False, dimming)  # 10 = blank
        
        # Fill from right to left
        for i, digit_char in enumerate(reversed(num_str)):
            tube_pos = self.num_tubes - 1 - i
            if tube_pos >= 0 and digit_char.isdigit():
                self.display_buffer[tube_pos] = (int(digit_char), color, True, False, dimming)
        
        # Handle leading zeros
        if leading_zeros:
            for i in range(self.num_tubes - len(num_str)):
                if self.display_buffer[i][0] == 10:  # If blank
                    self.display_buffer[i] = (0, color, True, False, dimming)
    
    def clear(self):
        """Clear all tubes"""
        for i in range(self.num_tubes):
            self.display_buffer[i] = (10, EASY_NIXIE_WHITE, True, False, 0)  # Blank and off
        self.update_display()
    
    def test_pattern(self):
        """Run a comprehensive test pattern"""
        print("Running EasyNixie test pattern...")
        
        # Test each digit with different colors
        colors = [EASY_NIXIE_WHITE, EASY_NIXIE_RED, EASY_NIXIE_GREEN, EASY_NIXIE_BLUE]
        
        for color in colors:
            print(f"Testing color: {color}")
            for digit in range(10):
                for tube in range(self.num_tubes):
                    self.set_tube(tube, digit, color, dimming=255)
                self.update_display()
                time.sleep(0.3)
        
        # Test counting
        print("Testing counting...")
        for count in range(min(100, 10**self.num_tubes)):
            self.set_number(count, EASY_NIXIE_WHITE, leading_zeros=True, dimming=128)
            self.update_display()
            time.sleep(0.05)
        
        self.clear()

def main():
    """Test with 0-99 counting"""
    # Pin configuration for Raspberry Pi Pico 2 W
    OUT_EN_PIN = board.GP21   # Output Enable
    SHCP_PIN = board.GP18     # Shift Clock  
    STCP_PIN = board.GP20     # Storage Clock
    DSIN_PIN = board.GP19     # Data Serial Input
    
    print("Initializing EasyNixie...")
    
    # Initialize with 2 tubes
    nixie = EasyNixie(
        out_en_pin=OUT_EN_PIN,
        shcp_pin=SHCP_PIN,
        stcp_pin=STCP_PIN,
        dsin_pin=DSIN_PIN,
        num_tubes=2
    )
    
    print(f"Testing {nixie.num_tubes} tubes...")
    
    # COUNT FROM 0 TO 99
    print("\n=== COUNTING FROM 0 TO 99 ===")
    for count in range(100):
        if count % 10 == 0:
            print(f"Count: {count}")
        if count < 99:
            nixie.set_number(count, EASY_NIXIE_WHITE, leading_zeros=True, dimming=128)
        else:
            nixie.set_number(count, EASY_NIXIE_RED, leading_zeros=True, dimming=64)
        nixie.update_display()
        time.sleep(0.08)
    
    print("Counting complete!\n")
    print("random numbers and dimming")
      
    for loops in range(50): 
        for count in range(20):
            if count % 10 == 0:
                print(f"Count: {count}")
            digit = random.randint(0,99)

            nixie.set_number(digit, EASY_NIXIE_GREEN, leading_zeros=True, dimming=64)
            nixie.update_display()
            time.sleep(0.08)
        
        for count in range(255):
            if count % 10 == 0:
                print(f"Count: {count}")
            nixie.set_number(digit, EASY_NIXIE_RED, leading_zeros=True, dimming=count)
            nixie.update_display()
            time.sleep(0.01)
    
    nixie.clear()

if __name__ == "__main__":
    main()