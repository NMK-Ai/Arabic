#!/usr/bin/env python3
import time
import inputs
import cereal.messaging as messaging

pub = messaging.pub_sock('carControl')
sub = messaging.sub_sock('carState')

enabled = False
accel = 0.0
steer = 0.0

def wait_for_car_start():
    print("🚙 في انتظار تشغيل السيارة...")
    while True:
        msg = sub.receive()
        if msg is None:
            continue
        if msg.which() == 'carState' and msg.carState.started:
            print("✅ السيارة شغالة. جاهز للتحكم.")
            break
        time.sleep(0.1)

def send_control(accel, steer, enabled):
    m = messaging.new_message('carControl')
    m.carControl.enabled = enabled
    m.carControl.accel = accel
    m.carControl.steer = steer
    pub.send(m.to_bytes())
    print(f"🚗 إرسال => enabled={enabled}, accel={accel:.2f}, steer={steer:.2f}")

def norm(val):
    return max(-1.0, min(1.0, val 
                         
if __name__ == "__main__":
    wait_for_car_start()
    print("🔁 التحكم باليد مفعّل. استخدم العصا اليسرى (A للتفعيل / B لإعادة التعيين)")

    while True:
        for event in inputs.get_gamepad():
            if event.code == 'ABS_Y':
                accel = -norm(event.state)
            elif event.code == 'ABS_X':
                steer = norm(event.state)
            elif event.code == 'BTN_SOUTH' and event.state == 1:
                enabled = not enabled
                print("🅰️ تبديل التفعيل:", "مفعّل" if enabled else "معطّل")
            elif event.code == 'BTN_EAST' and event.state == 1:
                accel = steer = 0.0
                enabled = False
                print("⛔ إعادة تعيين")
        send_control(accel, steer, enabled)
        time.sleep(0.05)
/ 32768.0))

if __name__ == "__main__":
    wait_for_car_start()
    print("🔁 التحكم باليد مفعل. استخدم العصا اليسرى (A للتفعيل / B لإعادة التعيين)")

    while True:
        for event in inputs.get_gamepad():
            if event.code == 'ABS_Y':
                accel = -norm(event.state)
            elif event.code == 'ABS_X':
                steer = norm(event.state)
            elif event.code == 'BTN_SOUTH' and event.state == 1:
                enabled = not enabled
                print("🅰️ تبديل التفعيل:", "مفعل" if enabled else "معطل")
            elif event.code == 'BTN_EAST' and event.state == 1:
                accel = steer = 0.0
                enabled = False
                print("⛔️ إعادة تعيين")
        send_control(accel, steer, enabled)
        time.sleep(0.05)
