"""Total Overdose (GOG build) car driving model, transcribed from the decompiled car_move_ctrl code, for flat ground.

This is the per-physics-step model of the 4-wheel car shell (car_move_ctrl = OverdoseVehicle, VehicleSedan.fragment).
Every line names the engine function it comes from (GOG TOD.exe, md5 d9beb351b3c78ee9f14a766a368f3ff9). It covers
the in-control states on level ground with all wheels touching: engine, drag, rolling resistance, coasting, brakes,
reverse, the steering ramp, the speed-dependent steering reduction, grip turning (exact kinematic bicycle), the slide
start, the slide (power-slide) state and the spin-out trigger. Not modelled: slopes and jumps, suspension (visual
only), collisions (RigidBody TestAndResolveCollision), the burnout and the handbrake spin (both described in the doc).

Frame of reference: vehicle-local, +z forward, +x sideways. The engine keeps two point velocities in local space
(front axle point, rear axle point; native OverdoseVehicle +0x288 / +0x298); the body's yaw rate is
(front.x - rear.x) / wheelbase (convert_forth 0x92CF10 -> RigidBody angular velocity), its velocity the average.

usage:
  vehsim.py TYPE [--set name=value ...]      prints the derived numbers for one VehicleDict type (needs vehtool's data)
  python -c "import vehsim; ..."             use simulate() / derived() from your own scripts
"""
import math

STEP = 0.04            # common.default_timestep (common class member +0x48, registration default 0.04)

# car_move_ctrl registration defaults (FUN_004FF2D0 region, reg 0x4FF302); none of these is set by shipped data
SHELL_DEFAULTS = dict(max_engine_force=12000.0, max_turn=0.785, turn_rate=0.174, burn_out_speed=10.0,
                      static_brake_resistance=1.0, max_reverse_force=6000.0, rolling_res=189.0, slide_angle=0.174,
                      rolling_static_threshold=1.0, powerslide_minimum_turnrate=0.5,
                      sideways_slide_resistance=0.95, sideways_static_resistance=0.1,
                      standard_sideways_slide_resistance=0.6, standard_sideways_static_resistance=0.1)

# code constants of the model (address of the float in .rdata, value)
CONST = dict(coast_mass_factor=1.5,      # DAT_009B74F4, 0x4F5E00 tail: no pedal -> effective mass x1.5
             slide_rear_gain=0.15,       # DAT_009BE2A4, 0x4D5A40: rear lateral = -wheel_angle*0.15*v*...
             slide_power=1.7,            # DAT_009BE224, 0x4D5A40: rolling resistance x1.7 while sliding
             reverse_corner_scale=0.6,   # DAT_009BE5B4, 0x4D96E0: reverse steering reduction x0.6
             slide_start_mult=0.1,       # DAT_009B38F4, 0x4D96E0: slide_multiplier += 0.1 at slide start
             control_rate=0.01)          # DAT_009B342C, 0x4D96E0: counter += control_speed*0.01 per step


def top_speed(F, c, r):
    """terminal speed of c v^2 + r v = F (car_move_ctrl reset 0x4E94C0 stores it as cornering_ref_speed)."""
    c = c if c != 0 else 1.0                                   # reset: drag_coeff 0 -> 1
    return (-r + math.sqrt(r * r + 4.0 * c * F)) / (c + c)


def params(row, shell=None, wheelbase=4.0):
    """model parameters from a VehicleDict row (dict of its properties) and the car_move_ctrl shell values."""
    s = dict(SHELL_DEFAULTS)
    s.update(shell or {})
    p = dict(s)
    p.update(F=s['max_engine_force'], Frev=s['max_reverse_force'], r=s['rolling_res'],
             c=row.get('drag_coeff', 1.0) or 1.0, m=row.get('Mass', 1000.0), B=row.get('BrakeForce', 12000.0),
             cs=row.get('cornering_stiffness', 1.0), lss=row.get('lateral_slide_speed', 20.0),
             front_slide_factor=row.get('front_slide_factor', 1.05), brake_slide_factor=row.get('brake_slide_factor', 5.0),
             brake_front_slide_factor=row.get('brake_front_slide_factor', 0.4), slide_factor=row.get('slide_factor', 5.0),
             control_speed=min(max(row.get('control_speed', 1.0), 0.0), 1000.0),
             time_to_slide_factor=row.get('time_to_slide_factor', 1.0), L=wheelbase)
    p['vmax'] = top_speed(p['F'], p['c'], p['r'])
    p['vrev'] = top_speed(p['Frev'], p['c'], p['r'])
    return p


class Car:
    def __init__(self, p):
        self.p = p
        self.vr = [0.0, 0.0]          # rear point velocity (x, z), local
        self.vf = [0.0, 0.0]          # front point velocity
        self.wa = 0.0                 # wheel_angle (rad), positive = right
        self.nfim = 1.0               # no_force_inertia_mass_factor
        self.sliding = False
        self.slide_mult = 1.0         # slide_multiplier
        self.bsm = 1.0                # brake_slide_multiplier
        self.counter = 0.0            # control_counter
        self.sign = 0.0               # control_angle_sign
        self.spun = False             # in_control = 0 (spin-out): the car leaves this model
        self.heading = 0.0
        self.pos = [0.0, 0.0]
        self.angle = 0.0

    def step(self, accel=False, decel=False, brake=False, steer=0.0, dt=STEP):
        p, C = self.p, CONST
        vr, vf = self.vr, self.vf
        # ---- forces FUN_004F5E00
        Fz = p['F'] if accel else 0.0                                       # key_accelerate & rear wheels grounded
        n = abs(steer)
        self.keynum = n
        if steer > 0:                                                       # key_right
            self.wa = min(max(self.wa + p['turn_rate'] * n, -p['max_turn'] * n), p['max_turn'] * n)
        elif steer < 0:                                                     # key_left
            self.wa = min(max(self.wa - p['turn_rate'] * n, -p['max_turn'] * n), p['max_turn'] * n)
        else:
            self.wa = 0.0                                                   # 0x4F60C5: instant re-centre
        if (brake or decel) and vr[1] > 0:                                  # brakes push along -z (FUN_00487E50 = (0,0,1))
            Fz -= p['B']
            if math.hypot(*vr) < p['static_brake_resistance']:
                self.vr = vr = [0.0, 0.0]; self.vf = vf = [0.0, 0.0]; Fz = 0.0
        if brake and vr[1] < 0:
            Fz += p['B']
            if math.hypot(*vr) < p['static_brake_resistance']:
                self.vr = vr = [0.0, 0.0]; self.vf = vf = [0.0, 0.0]; Fz = 0.0
        if decel and vf[1] <= 0:                                            # reverse gear
            Fz -= p['Frev']
        # 0x4F5E00 tail: S while still rolling forward counts as 'no pedal' (coasting factor), so S brakes at 1/1.5 of V
        pedal = accel or brake or (decel and vf[1] < 0)
        if pedal:
            self.nfim = 1.0
        elif self.nfim != 1.0:
            if abs(vr[1]) < p['rolling_static_threshold']:
                vr[1] = 0.0; self.nfim = 1.0
        else:
            self.nfim = C['coast_mass_factor']
        # ---- gravity / grip FUN_004E5F00: grounded and not sliding -> lateral point velocity removed
        if not self.sliding:
            vr[0] = 0.0; vf[0] = 0.0
        # ---- rear drive FUN_004F1B50
        sp = C['slide_power'] if self.sliding else 1.0                      # slide_power_factor
        fz = Fz - math.hypot(*vr) * p['c'] * vr[1] - sp * p['r'] * vr[1]
        vr[1] += fz * dt / (self.nfim * p['m'])
        # ---- steering FUN_004F8BF0
        a = self.wa
        if abs(self.wa) > 0.01:
            self._turn(a, dt)
        else:
            self._straight(dt)
        # ---- body
        L = p['L']
        omega = (vf[0] - vr[0]) / L
        self.heading += omega * dt
        vx, vz = (vf[0] + vr[0]) * 0.5, (vf[1] + vr[1]) * 0.5
        ch, sh = math.cos(self.heading), math.sin(self.heading)
        self.pos[0] += (vx * ch + vz * sh) * dt
        self.pos[1] += (-vx * sh + vz * ch) * dt
        # spin-out check of the drive handler 0x4F9C80 (per frame; here per step)
        if p['slide_factor'] > 0 and self.counter >= p['slide_factor'] * 2.0 * p['time_to_slide_factor']:
            self.spun = True
        return omega

    def _turn(self, a, dt):                                                  # FUN_004D96E0
        p, C = self.p, CONST
        vr, vf = self.vr, self.vf
        if vr[1] > 1e-4:
            a *= min(max(1.0 - vr[1] / p['vmax'] * p['cs'], 0.001), 1.0)
        if vr[1] < 1e-4:
            a *= min(max(vr[1] / p['vrev'] * p['cs'] * C['reverse_corner_scale'] + 1.0, 0.001), 1.0)
        self.angle = a
        if not self.sliding:
            if abs(self.wa) - abs(a) >= p['slide_angle'] and vr[1] > p['lss']:
                self.sliding = True
                self.slide_mult += C['slide_start_mult']
            if not self.sliding:
                self.slide_mult = 1.0
        if self.bsm > 1.01:
            self.bsm = max(self.bsm + 0.3, self.slide_mult)
            self.bsm = min(self.bsm, p['brake_slide_factor'])
        power = getattr(self, 'keynum', 0.0) > p['powerslide_minimum_turnrate']   # key_left/right_number (keyboard = 1)
        if self.slide_mult > 1.01 and power:
            self.slide_mult = min(self.slide_mult + p['control_speed'] * C['control_rate'], p['slide_factor'])
        if self.sliding and power:
            self.counter += p['control_speed'] * C['control_rate']
            if a * self.sign < 0:
                self.counter = 0.0
            self.sign = a
        s = dt * vr[1]
        d = (math.sin(a), math.cos(a))                                       # front point direction (rotated by angle)
        L = p['L']
        if self.sliding and s > 0:                                           # FUN_004D5A40
            if self.bsm == 1.0:
                vr[0] = -(self.wa * C['slide_rear_gain'] * vr[1] * self.slide_mult)
            else:
                vr[0] = -(self.wa * C['slide_rear_gain'] * vr[1] * self.bsm * self.bsm)
            t = dt * vr[0]
            x = ((L - s) - (math.sin(math.pi / 2 - a) * t) / math.sin(a)) * math.sin(math.pi - a) / L
            b = math.asin(min(max(x, -0.99), 0.99))
            k = ((L * math.sin(a - b)) / math.sin(math.pi - a) - t / math.sin(a)) / dt
            vf[0], vf[1] = d[0] * k, d[1] * k
            f = p['front_slide_factor'] if self.bsm == 1.0 else p['brake_front_slide_factor']
            vf[0] += f * vr[0]
            return
        k = 0.0                                                              # FUN_004D6390 grip
        if 0 < s < 2 * L:
            x = min(max((L - s) * math.sin(math.pi - a) / L, -0.99), 0.99)
            k = math.sin(a - math.asin(x)) * L / (math.sin(math.pi - a) * dt)
        elif -2 * L < s < 0:
            x = min(max(((-s) + L) * math.sin(a) / L, -0.99), 0.99)
            q = math.asin(x)
            q = (math.pi - q) if q > 0 else ((-math.pi - q) if q < 0 else q)
            k = math.sin((math.pi - a) - q) * L / (math.sin(a) * dt)
        vf[0], vf[1] = d[0] * k, d[1] * k

    def _straight(self, dt):                                                 # FUN_004F2040
        p = self.p
        vr, vf = self.vr, self.vf
        self.counter = 0.0
        if self.sliding:
            k = p['sideways_slide_resistance'] if self.bsm > 1.0 else p['standard_sideways_slide_resistance']
            vr[0] *= k; vf[0] *= k
            if abs(vr[0]) < p['sideways_static_resistance']:
                vr[0] = 0.0; vf[0] = 0.0
                self.sliding = False; self.bsm = 1.0
        vf[1] = vr[1]

    def speed(self):
        return self.vr[1]


def accel_time(p, target, tmax=60.0):
    c = Car(p); t = 0.0
    while t < tmax:
        if c.speed() >= target:
            return t
        c.step(accel=True); t += STEP
    return None


def brake_distance(p, v0, use='brake'):
    c = Car(p); c.vr = [0.0, v0]; c.vf = [0.0, v0]; t = 0.0; dist = 0.0
    while c.speed() > 0 and t < 30:
        c.step(brake=(use == 'brake'), decel=(use == 'decel'))
        dist += max(c.speed(), 0) * STEP; t += STEP
    return dist, t


def coast_distance(p, v0):
    c = Car(p); c.vr = [0.0, v0]; c.vf = [0.0, v0]; t = 0.0; dist = 0.0
    while c.speed() > 0 and t < 120:
        c.step(); dist += c.speed() * STEP; t += STEP
    return dist, t


def turn_at(p, v, steer=1.0, seconds=3.0, accel=True):
    """hold full steering at speed v (keeping the throttle); returns yaw rate, radius, lateral g, slide/spin times."""
    c = Car(p); c.vr = [0.0, v]; c.vf = [0.0, v]
    t = 0.0; slide_t = spin_t = None; om = 0.0
    while t < seconds:
        om = c.step(accel=accel and c.speed() < v, steer=steer); t += STEP
        if c.sliding and slide_t is None:
            slide_t = t
        if c.spun:
            spin_t = t; break
    sp = c.speed()
    radius = sp / abs(om) if om else float('inf')
    return dict(yaw_deg_s=math.degrees(om), radius=radius, lat_g=sp * abs(om) / 9.81 if om else 0.0,
                effective_angle_deg=math.degrees(c.angle), slide_at=slide_t, spin_at=spin_t, end_speed=sp)


def derived(p):
    vmax, vrev = p['vmax'], p['vrev']
    out = dict(top_speed_kmh=vmax * 3.6, reverse_top_kmh=vrev * 3.6,
               t_0_50=accel_time(p, 50 / 3.6), t_0_100=accel_time(p, 100 / 3.6),
               t_0_90pct=accel_time(p, 0.9 * vmax),
               brake_100_m=None, coast_from_top_m=None,
               steer_gone_kmh=(vmax / p['cs'] * 3.6) if p['cs'] > 0 else None,
               steer_factor_50=max(min(1 - (50 / 3.6) / vmax * p['cs'], 1), 0.001),
               steer_factor_100=max(min(1 - (100 / 3.6) / vmax * p['cs'], 1), 0.001),
               lock_time_s=math.ceil(p['max_turn'] / p['turn_rate']) * STEP,
               min_radius_m=p['L'] / math.sin(p['max_turn']),
               slide_possible_kmh=p['lss'] * 3.6)
    if vmax > 100 / 3.6:
        out['brake_100_m'], out['brake_100_s'] = brake_distance(p, 100 / 3.6)
    out['coast_from_top_m'], out['coast_from_top_s'] = coast_distance(p, vmax * 0.999)
    # slide onset needs |wheel| - |angle| >= slide_angle: |angle| = max_turn*f(v) -> f(v) <= 1 - slide_angle/max_turn
    need = 1 - p['slide_angle'] / p['max_turn']
    v_slide = (1 - need) / p['cs'] * vmax if p['cs'] > 0 else float('inf')
    out['slide_onset_kmh'] = max(v_slide, p['lss']) * 3.6
    return out


if __name__ == '__main__':
    import sys
    print(__doc__)
