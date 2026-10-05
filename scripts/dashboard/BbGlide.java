import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.MotionEvent;
import java.lang.reflect.Method;

/**
 * One held touch stroke through the points: BbGlide MS X Y X Y...
 *
 * bb phone touch glide on an unrooted phone (R126). `input motionevent` is a
 * process per event, each with its own down-time and a few hundred
 * milliseconds to start on a real phone, so a keyboard saw taps where a glide
 * was meant (report #56: h-e-l-l-o typed "Hakt1"). The shell user may inject
 * input; this injects DOWN, a MOVE every ~8 ms along each segment (MS apart
 * from point to point) and UP, all with one down-time, the way scrcpy does.
 * Built on the node with its own javac and d8 and run with app_process.
 */
public final class BbGlide {
    public static void main(String[] a) throws Exception {
        long step = Long.parseLong(a[0]);
        int n = (a.length - 1) / 2;
        float[] xs = new float[n], ys = new float[n];
        for (int i = 0; i < n; i++) {
            xs[i] = Float.parseFloat(a[1 + 2 * i]);
            ys[i] = Float.parseFloat(a[2 + 2 * i]);
        }
        Object im;
        Method inject;
        try {
            Class<?> c = Class.forName("android.hardware.input.InputManagerGlobal");
            im = c.getMethod("getInstance").invoke(null);
            inject = c.getMethod("injectInputEvent", InputEvent.class, int.class);
        } catch (ReflectiveOperationException e) {
            Class<?> c = Class.forName("android.hardware.input.InputManager");
            im = c.getMethod("getInstance").invoke(null);
            inject = c.getMethod("injectInputEvent", InputEvent.class, int.class);
        }
        long down = SystemClock.uptimeMillis();
        send(im, inject, down, down, MotionEvent.ACTION_DOWN, xs[0], ys[0]);
        for (int i = 1; i < n; i++) {
            int sub = (int) Math.max(1, step / 8);
            for (int k = 1; k <= sub; k++) {
                float t = (float) k / sub;
                Thread.sleep(Math.max(1, step / sub));
                send(im, inject, down, SystemClock.uptimeMillis(), MotionEvent.ACTION_MOVE,
                     xs[i - 1] + (xs[i] - xs[i - 1]) * t, ys[i - 1] + (ys[i] - ys[i - 1]) * t);
            }
        }
        send(im, inject, down, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, xs[n - 1], ys[n - 1]);
    }

    private static void send(Object im, Method inject, long down, long at, int action, float x, float y)
            throws Exception {
        MotionEvent e = MotionEvent.obtain(down, at, action, x, y, 0);
        e.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        inject.invoke(im, e, 2);    // INJECT_INPUT_EVENT_MODE_WAIT_FOR_FINISH
        e.recycle();
    }
}
