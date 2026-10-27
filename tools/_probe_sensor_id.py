# -*- coding: utf-8 -*-
import sensor, time
sensor.reset()
time.sleep_ms(200)
for fn in ("get_id",):
    try:
        print("[ID] %s() = %r" % (fn, getattr(sensor, fn)()))
    except Exception as e:
        print("[ID] %s err %r" % (fn, e))
try:
    print("[ID] reset 后再读 = %r" % (sensor.get_id(),))
except Exception as e:
    print("[ID] err %r" % (e,))
print("[ID] DONE")
