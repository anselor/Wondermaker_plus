# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-bound resonance stop points and restoration for both WM executors."""
import copy
import inspect
import math


class ResonanceStop:
    def __init__(self, stops, tester, original):
        self.stops, self.tester, self.original = stops, tester, original

    def __call__(self, *args, **kwargs):
        calibration = self.stops._calibration_wait_owner()
        if calibration is None:
            return self.original(*args, **kwargs)
        printer = calibration.printer
        gcode = printer.lookup_object('gcode')
        toolhead = printer.lookup_object('toolhead')
        attempt = calibration.executing
        tracker = calibration._heater_ownership
        actor = tracker.current_actor()
        patches, clients = [], []
        now = printer.get_reactor().monotonic()
        status = toolhead.get_status(now)
        limits = {key: float(status[key]) for key in
                  ('max_velocity', 'max_accel', 'minimum_cruise_ratio')}
        if (not all(math.isfinite(value) for value in limits.values())
                or limits['max_velocity'] <= 0 or limits['max_accel'] <= 0
                or not 0 <= limits['minimum_cruise_ratio'] <= 1):
            raise gcode.error('Vibration calibration cannot verify motion limits')
        shaper = printer.lookup_object('input_shaper', None)
        axes = [] if shaper is None else list(shaper.get_shapers())
        shaping = [(axis, copy.deepcopy((axis.n, axis.A, axis.T, axis.saved))) for axis in axes]
        if shaper is not None and not callable(getattr(shaper, '_update_input_shaping', None)):
            raise gcode.error('Vibration calibration cannot restore input shaping')

        def owned():
            return tracker.current_actor() is actor

        def check(label):
            if not owned():
                return
            if self.stops._calibration_wait_owner() is not calibration:
                raise gcode.error('Vibration calibration command owner changed')
            calibration.check_cancel(label, attempt)

        def patch(obj, name, wrapper):
            original = getattr(obj, name)
            local = name in vars(obj)
            replacement = wrapper(original)
            setattr(obj, name, replacement)
            patches.append((obj, name, original, replacement, local))

        def boundary(label):
            def wrap(original):
                def guarded(*values, **options):
                    check(label)
                    return original(*values, **options)
                return guarded
            return wrap

        def finish_client(original):
            def finish(*values, **options):
                check('before vibration recording completion')
                result = original(*values, **options)
                check('after vibration recording completion')
                return result
            return finish

        def start_client(original):
            def start(*values, **options):
                if owned():
                    check('before vibration recording')
                client = original(*values, **options)
                if owned():
                    clients.append(client)
                    if not callable(getattr(client, 'finish_measurements', None)):
                        raise gcode.error('Vibration recording cannot be closed')
                    patch(client, 'finish_measurements', finish_client)
                return client
            return start

        # Bind the real factory/backport signature, including explicitly selected
        # CHIPS. Do not patch every accelerometer on the printer.
        selected = inspect.signature(self.original).bind(*args, **kwargs).arguments.get('accel_chips')
        chips = list(selected) if selected is not None else [chip for _, chip in self.tester.accel_chips]
        unique_chips = {id(chip): chip for chip in chips}.values()
        try:
            check('before vibration calibration')
            for name, label in (('move', 'between vibration segments'),
                                ('manual_move', 'before vibration travel'),
                                ('dwell', 'before vibration dwell')):
                patch(toolhead, name, boundary(label))
            for chip in unique_chips:
                patch(chip, 'start_internal_client', start_client)
            result = self.original(*args, **kwargs)
            check('after vibration measurements')
            return result
        finally:
            errors = []
            # The guard is per command, not a permanent motor/motion wrapper.
            # Remove it before draining moves and closing measurement clients.
            for obj, name, original, replacement, local in reversed(patches):
                if getattr(obj, name) is replacement:
                    if local:
                        setattr(obj, name, original)
                    else:
                        delattr(obj, name)
                else:
                    errors.append('Vibration hook ownership changed: ' + name)
            for client in clients:
                if not getattr(client, 'is_finished', False):
                    try:
                        client.finish_measurements()
                    except Exception as error:
                        errors.append('Vibration recording close failed: ' + str(error))
            try:
                toolhead.wait_moves()
                if printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False):
                    raise ValueError('Printer stopped; vibration motion settings unconfirmed')
                current = toolhead.get_status(printer.get_reactor().monotonic())
                if any(current[key] != value for key, value in limits.items()):
                    gcode.run_script_from_command(
                        'SET_VELOCITY_LIMIT VELOCITY=%.17g ACCEL=%.17g MINIMUM_CRUISE_RATIO=%.17g'
                        % (limits['max_velocity'], limits['max_accel'], limits['minimum_cruise_ratio']))
                current = toolhead.get_status(printer.get_reactor().monotonic())
                if any(not math.isclose(current[key], value, rel_tol=1e-12, abs_tol=1e-12)
                       for key, value in limits.items()):
                    raise ValueError('Vibration motion limit restoration was not confirmed')
            except Exception as error:
                errors.append(str(error))
            try:
                if shaper is not printer.lookup_object('input_shaper', None):
                    raise ValueError('Vibration input shaper owner changed')
                if shaper is not None:
                    if any(current is not saved for current, saved in zip(shaper.get_shapers(), axes)) or len(shaper.get_shapers()) != len(axes):
                        raise ValueError('Vibration input shaper axes changed')
                    changed = any((axis.n, axis.A, axis.T, axis.saved) != state for axis, state in shaping)
                    if changed and (printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False)):
                        raise ValueError('Printer stopped; vibration input shaping unconfirmed')
                    for axis, state in shaping:
                        if (axis.n, axis.A, axis.T, axis.saved) != state:
                            axis.n, axis.A, axis.T, axis.saved = copy.deepcopy(state)
                    if changed:
                        shaper._update_input_shaping()
                    if any((axis.n, axis.A, axis.T, axis.saved) != state for axis, state in shaping):
                        raise ValueError('Vibration input shaping restoration was not confirmed')
            except Exception as error:
                errors.append(str(error))
            if errors:
                message = 'Vibration cleanup unconfirmed: ' + '; '.join(errors)
                attempt['cancel_motion_error'] = message[:512]
                raise gcode.error(message[:512])


def install_calculation_stop(original_run):
    """Install once on the helper shared by the factory/backported tester.

    Unbound/CLI uses retain their original method. The managed method uses one
    result message for any Python return type; reading as soon as the pipe is
    ready also avoids waiting for a child blocked on a large result write.
    """
    namespace = getattr(getattr(original_run, '__func__', None), '__globals__', {})
    module = namespace.get('shaper_calibrate')
    helper_class = getattr(module, 'ShaperCalibrate', None)
    original = getattr(helper_class, 'background_process_exec', None)
    if not callable(original) or getattr(original, '_wmp_calculation_stop', False):
        return
    def background_process_exec(helper, method, args):
        printer = helper.printer
        material = None if printer is None else printer.lookup_object('wm_material', None)
        accessor = getattr(material, '_stop_points', None)
        stops = accessor() if callable(accessor) else None
        calibration = None if stops is None else stops._calibration_wait_owner()
        if calibration is None:
            return original(helper, method, args)
        return run_calculation(stops, calibration, helper, method, args)
    background_process_exec._wmp_calculation_stop = True
    helper_class.background_process_exec = background_process_exec


def run_calculation(stops, calibration, helper, method, args):
    """Own and reap the fitting child; never stop motors or restart Klipper."""
    import multiprocessing
    import traceback
    printer = calibration.printer
    attempt = calibration.executing
    reactor = printer.get_reactor()
    gcode = printer.lookup_object('gcode')

    def check():
        if stops._calibration_wait_owner() is not calibration or calibration.executing is not attempt:
            raise helper.error('Shaper calculation command owner changed')
        calibration.check_cancel('during shaper calculations', attempt)

    check()
    parent, child = multiprocessing.Pipe()
    process = None
    started = False
    try:
        def calculate():
            import queuelogger
            parent.close()
            queuelogger.clear_bg_logging()
            try:
                try:
                    result = (False, method(*args))
                except BaseException:
                    result = (True, traceback.format_exc())
                child.send(result)
            finally:
                child.close()
        process = multiprocessing.Process(target=calculate)
        process.daemon = True
        process.start()
        started = True
        child.close()
        eventtime = last_report = reactor.monotonic()
        while not parent.poll():
            check()
            if not process.is_alive():
                # A child can exit between poll() and is_alive(). Recheck data
                # before treating a normal final write as a missing result.
                if parent.poll():
                    break
                raise helper.error('Shaper calculation ended without a result')
            if eventtime > last_report + 5.:
                last_report = eventtime
                gcode.respond_info('Wait for calculations..', log=False)
            eventtime = reactor.pause(eventtime + .1)
        check()
        try:
            failed, result = parent.recv()
        except EOFError:
            raise helper.error('Shaper calculation ended without a result')
        check()
        while process.is_alive():
            check()
            eventtime = reactor.pause(eventtime + .1)
        process.join()
        if failed:
            raise helper.error('Error in remote calculation: %s' % result)
        return result
    finally:
        errors = []
        try:
            if process is not None and (started or process.pid is not None):
                if process.is_alive():
                    try:
                        process.terminate()
                    except Exception:
                        pass  # Still try join/kill; never strand a fitting child.
                process.join(timeout=.2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=.2)
                if process.is_alive():
                    raise ValueError('Shaper calculation child did not stop')
                process.close()
            elif process is not None:
                process.close()
        except Exception as error:
            errors.append(str(error))
        for connection in (parent, child):
            try:
                connection.close()
            except Exception as error:
                errors.append(str(error))
        if errors:
            message = 'Shaper calculation cleanup unconfirmed: ' + '; '.join(errors)
            attempt['cancel_motion_error'] = message[:512]
            raise helper.error(message[:512])
