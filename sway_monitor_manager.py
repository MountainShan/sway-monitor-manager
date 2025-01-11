#!/usr/bin/env python3
import json
import gi
import subprocess
import os
from pathlib import Path
import cairo
from gi.repository import Gtk, Gio, GLib, Gdk

gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

CONFIG_PATH = Path.home() / '.config' / 'sway-monitor-config.json'
PROFILES_PATH = Path.home() / '.config' / 'sway-monitor-profiles'

class MonitorConfig:
    def __init__(self):
        self.name = ""
        self.model = ""
        self.position = "0,0"
        self.resolution = "1920x1080"
        self.scale = 1.0
        self.rotation = "normal"
        self.enabled = True

class MonitorPreviewArea(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.monitors = []
        self.set_draw_func(self.draw)
        self.set_content_width(300)
        self.set_content_height(200)
        
        # Add gesture support
        self.drag_gesture = Gtk.GestureDrag.new()
        self.drag_gesture.connect('drag-begin', self.on_drag_begin)
        self.drag_gesture.connect('drag-update', self.on_drag_update)
        self.drag_gesture.connect('drag-end', self.on_drag_end)
        self.add_controller(self.drag_gesture)
        
        self.active_monitor = None
        self.drag_start_pos = None
        self.scale = 1.0

    def get_monitor_at_position(self, x, y):
        if not self.monitors:
            return None
            
        # Convert coordinates to monitor space
        x = (x - 10) / self.scale
        y = (y - 10) / self.scale
        
        for monitor in self.monitors:
            if not monitor.enabled_switch.get_active():
                continue
                
            config = monitor.get_config()
            mx, my = map(int, config['position'].split(','))
            mw, mh = map(int, config['resolution'].split('x'))
            
            if (mx <= x <= mx + mw and 
                my <= y <= my + mh):
                return monitor
        return None

    def on_drag_begin(self, gesture, start_x, start_y):
        self.active_monitor = self.get_monitor_at_position(start_x, start_y)
        if self.active_monitor:
            config = self.active_monitor.get_config()
            self.drag_start_pos = tuple(map(int, config['position'].split(',')))

    def on_drag_update(self, gesture, offset_x, offset_y):
        if self.active_monitor and self.drag_start_pos:
            # Convert offset to monitor space
            dx = int(offset_x / self.scale)
            dy = int(offset_y / self.scale)
            
            # Update position
            new_x = self.drag_start_pos[0] + dx
            new_y = self.drag_start_pos[1] + dy
            
            # Update entry
            self.active_monitor.pos_entry.set_text(f"{new_x},{new_y}")
            self.queue_draw()

    def on_drag_end(self, gesture, offset_x, offset_y):
        self.active_monitor = None
        self.drag_start_pos = None

    def draw(self, area, cr, width, height):
        # Clear background
        cr.set_source_rgb(0.2, 0.2, 0.2)
        cr.paint()
        
        if not self.monitors:
            return
            
        # Calculate scale to fit all monitors
        max_x = max(int(m.get_config()['position'].split(',')[0]) + 
                   int(m.get_config()['resolution'].split('x')[0]) 
                   for m in self.monitors)
        max_y = max(int(m.get_config()['position'].split(',')[1]) + 
                   int(m.get_config()['resolution'].split('x')[1]) 
                   for m in self.monitors)
        
        scale_x = (width - 20) / max_x if max_x > 0 else 1
        scale_y = (height - 20) / max_y if max_y > 0 else 1
        self.scale = min(scale_x, scale_y)
        
        # Draw each monitor
        for i, monitor in enumerate(self.monitors):
            if not monitor.enabled_switch.get_active():
                continue
                
            config = monitor.get_config()
            x, y = map(int, config['position'].split(','))
            w, h = map(int, config['resolution'].split('x'))
            
            # Draw monitor rectangle
            if monitor == self.active_monitor:
                cr.set_source_rgb(0.4, 0.8, 1.0)  # Highlight active monitor
            else:
                cr.set_source_rgb(0.3, 0.6, 0.9)
            cr.rectangle(10 + x * self.scale, 10 + y * self.scale, 
                        w * self.scale, h * self.scale)
            cr.fill()
            
            # Draw monitor label and resolution
            cr.set_source_rgb(1, 1, 1)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(12)
            cr.move_to(10 + x * self.scale + 5, 10 + y * self.scale + 20)
            cr.show_text(f"{monitor.model}")
            cr.move_to(10 + x * self.scale + 5, 10 + y * self.scale + 40)
            cr.show_text(f"{w}x{h} ({x},{y})")
            
            # Draw resolution proportion indicator
            aspect_ratio = w / h
            indicator_width = 40
            indicator_height = indicator_width / aspect_ratio
            cr.rectangle(10 + x * self.scale + 5, 
                        10 + y * self.scale + 45,
                        indicator_width, indicator_height)
            cr.set_source_rgba(1, 1, 1, 0.3)
            cr.fill()
    
    def update_monitors(self, monitors):
        self.monitors = monitors
        self.queue_draw()

class SwayMonitorManager(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.example.swaymonitor',
                        flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.monitors = {}
        self.saved_configs = {}
        self.profiles = {}
        self.current_profile = "(Current)"
        self.load_saved_configs()
        self.load_profiles()
        self.save_current_config()

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = SwayMonitorWindow(application=self)
        win.present()

    def load_saved_configs(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r') as f:
                self.saved_configs = json.load(f)

    def load_profiles(self):
        if not PROFILES_PATH.exists():
            PROFILES_PATH.mkdir(parents=True, exist_ok=True)
            return

        for profile_file in PROFILES_PATH.glob('*.json'):
            profile_name = profile_file.stem
            with open(profile_file, 'r') as f:
                self.profiles[profile_name] = json.load(f)

    def save_current_config(self):
        """Save current monitor configuration as (Current) profile"""
        current_config = {}
        monitors = self.get_current_monitors()
        
        for monitor in monitors:
            model = monitor.get('model', '')
            if model:
                current_config[model] = {
                    'model': model,
                    'position': f"{monitor.get('rect', {}).get('x', 0)},{monitor.get('rect', {}).get('y', 0)}",
                    'resolution': f"{monitor.get('current_mode', {}).get('width', 1920)}x{monitor.get('current_mode', {}).get('height', 1080)}",
                    'scale': float(monitor.get('scale', 1.0)),
                    'enabled': not monitor.get('disabled', False),
                    'transform': monitor.get('transform', 'normal')
                }
        
        self.profiles["(Current)"] = current_config

    def save_configs(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self.saved_configs, f, indent=2)

    def save_profile(self, name, config):
        if name != "(Current)":
            profile_path = PROFILES_PATH / f"{name}.json"
            with open(profile_path, 'w') as f:
                json.dump(config, f, indent=2)
        self.profiles[name] = config

    def update_profile(self, name, config):
        if name in self.profiles:
            self.save_profile(name, config)
            return True
        return False

    def remove_profile(self, name):
        if name == "(Current)":
            return False
        profile_path = PROFILES_PATH / f"{name}.json"
        if profile_path.exists():
            profile_path.unlink()
            del self.profiles[name]
            return True
        return False

    def get_current_monitors(self):
        try:
            output = subprocess.check_output(['swaymsg', '-t', 'get_outputs'], 
                                          universal_newlines=True)
            return json.loads(output)
        except subprocess.CalledProcessError:
            return []

class SwayMonitorWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.set_title("Sway Monitor Manager")
        self.set_default_size(800, 600)

        # Main vertical box
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(vbox)

        # Profile selector
        profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vbox.append(profile_box)

        profile_label = Gtk.Label(label="Profile:")
        profile_box.append(profile_label)

        self.profile_combo = Gtk.ComboBoxText()
        self.refresh_profile_list()
        self.profile_combo.connect('changed', self.on_profile_changed)
        profile_box.append(self.profile_combo)

        # Add preview area above the monitor list
        self.preview_area = MonitorPreviewArea()
        vbox.append(self.preview_area)

        # Monitor list
        self.monitor_list = Gtk.ListBox()
        self.monitor_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.monitor_list)
        scrolled.set_vexpand(True)
        vbox.append(scrolled)

        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vbox.append(button_box)

        refresh_button = Gtk.Button(label="Refresh Monitors")
        refresh_button.connect("clicked", self.refresh_monitors)
        profile_box.append(refresh_button)
        
        apply_button = Gtk.Button(label="Apply Profiles")
        apply_button.connect("clicked", self.apply_configuration)
        button_box.append(apply_button)

        save_button = Gtk.Button(label="Save Profiles")
        save_button.connect("clicked", self.save_as_profile)
        button_box.append(save_button)

        # Add Update Profile button
        update_profile_button = Gtk.Button(label="Update Profile")
        update_profile_button.connect("clicked", self.update_profile)
        button_box.append(update_profile_button)

        # Add Remove Profile button
        remove_profile_button = Gtk.Button(label="Remove Profile")
        remove_profile_button.connect("clicked", self.remove_profile)
        button_box.append(remove_profile_button)
        
        # Initialize with "(Current)" profile
        self.props.application.saved_configs = self.props.application.profiles["(Current)"]
        self.refresh_monitors()

    def refresh_profile_list(self):
        self.profile_combo.remove_all()
        profiles = list(self.props.application.profiles.keys())
        # Ensure "(Current)" is first by removing and inserting at start if needed
        if "(Current)" in profiles:
            profiles.remove("(Current)")
            profiles.insert(0, "(Current)")
        # Add all profiles to combo box
        for profile in profiles:
            self.profile_combo.append_text(profile)
        # Select "(Current)" profile if it exists, otherwise select first profile
        try:
            current_idx = profiles.index("(Current)")
            self.profile_combo.set_active(current_idx)
        except ValueError:
            self.profile_combo.set_active(0)

    def remove_profile(self, button):
        profile_name = self.profile_combo.get_active_text()
        if self.props.application.remove_profile(profile_name):
            self.refresh_profile_list()

    def update_profile(self, button):
        profile_name = self.profile_combo.get_active_text()
        if profile_name != "(Current)":
            configs = {}
            for row in self.monitor_list:
                if isinstance(row, MonitorConfigRow):
                    config = row.get_config()
                    configs[config['model']] = config
            if self.props.application.update_profile(profile_name, configs):
                self.refresh_profile_list()

    def on_profile_changed(self, combo):
        profile_name = combo.get_active_text()
        if profile_name in self.props.application.profiles:
            self.props.application.saved_configs = self.props.application.profiles[profile_name]
            self.refresh_monitors()

    def save_as_profile(self, button):
        dialog = Gtk.Dialog(title="Save Profile", parent=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_placeholder_text("Profile name")
        box.append(entry)
        box.show()

        dialog.connect("response", self.on_save_profile_response, entry)
        dialog.present()

    def on_save_profile_response(self, dialog, response, entry):
        if response == Gtk.ResponseType.OK:
            profile_name = entry.get_text()
            if profile_name:
                configs = {}
                for row in self.monitor_list:
                    if isinstance(row, MonitorConfigRow):
                        config = row.get_config()
                        configs[config['model']] = config
                self.props.application.save_profile(profile_name, configs)
                self.refresh_profile_list()
                
                # Set the new profile as active
                model = self.profile_combo.get_model()
                for i in range(len(model)):
                    if model[i] == profile_name:
                        self.profile_combo.set_active(i)
                        break

        dialog.destroy()

    def refresh_monitors(self, button=None):
        # Clear existing monitors
        while True:
            row = self.monitor_list.get_first_child()
            if row is None:
                break
            self.monitor_list.remove(row)

        # Get current monitors
        monitors = self.props.application.get_current_monitors()
        monitor_rows = []
        
        for monitor in monitors:
            row = MonitorConfigRow(monitor, self.props.application.saved_configs)
            self.monitor_list.append(row)
            monitor_rows.append(row)
            
            # Connect signals for live preview updates
            row.pos_entry.connect('changed', self.on_config_changed)
            row.res_entry.connect('changed', self.on_config_changed)
            row.enabled_switch.connect('state-set', self.on_config_changed)
            row.scale_entry.connect('changed', self.on_config_changed)
            row.transform_combo.connect('changed', self.on_config_changed)
            
        self.preview_area.update_monitors(monitor_rows)

    def on_config_changed(self, widget, *args):
        self.preview_area.queue_draw()

    def apply_configuration(self, button):
        for row in self.monitor_list:
            if isinstance(row, MonitorConfigRow):
                row.apply_config()

class MonitorConfigRow(Gtk.ListBoxRow):
    def __init__(self, monitor_data, saved_configs):
        super().__init__()
        
        self.monitor_data = monitor_data
        self.model = monitor_data.get('model', '')
        
        # Load saved config if exists
        saved_config = saved_configs.get(self.model, {})

        # Main container
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(box)

        # Monitor info
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(info_box)

        name_label = Gtk.Label(label=f"Name: {monitor_data.get('name', 'Unknown')}")
        info_box.append(name_label)

        model_label = Gtk.Label(label=f"Model: {self.model}")
        info_box.append(model_label)

        # Configuration options
        config_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(config_box)

        # Position
        pos_label = Gtk.Label(label="Position:")
        config_box.append(pos_label)
        self.pos_entry = Gtk.Entry()
        self.pos_entry.set_text(saved_config.get('position', '0,0'))
        config_box.append(self.pos_entry)

        # Resolution
        res_label = Gtk.Label(label="Resolution:")
        config_box.append(res_label)
        self.res_entry = Gtk.Entry()
        self.res_entry.set_text(saved_config.get('resolution', 
                              f"{monitor_data.get('current_mode', {}).get('width', 1920)}x"
                              f"{monitor_data.get('current_mode', {}).get('height', 1080)}"))
        config_box.append(self.res_entry)

        # Scale
        scale_label = Gtk.Label(label="Scale:")
        config_box.append(scale_label)
        self.scale_entry = Gtk.Entry()
        self.scale_entry.set_text(str(saved_config.get('scale', 1.0)))
        config_box.append(self.scale_entry)

        # Enable/Disable
        self.enabled_switch = Gtk.Switch()
        self.enabled_switch.set_active(saved_config.get('enabled', True))
        config_box.append(self.enabled_switch)

        # Add transform option
        transform_label = Gtk.Label(label="Transform:")
        config_box.append(transform_label)
        
        self.transform_combo = Gtk.ComboBoxText()
        transforms = ["normal", "90", "180", "270", "flipped", 
                     "flipped-90", "flipped-180", "flipped-270"]
        for transform in transforms:
            self.transform_combo.append_text(transform)
        
        saved_transform = saved_config.get('transform', 'normal')
        self.transform_combo.set_active(transforms.index(saved_transform))
        config_box.append(self.transform_combo)

        # Connect transform signal
        self.transform_combo.connect('changed', self.on_transform_changed)

    def get_config(self):
        config = {
            'model': self.model,
            'position': self.pos_entry.get_text(),
            'resolution': self.res_entry.get_text(),
            'scale': float(self.scale_entry.get_text()),
            'enabled': self.enabled_switch.get_active(),
            'transform': self.transform_combo.get_active_text()
        }
        return config

    def apply_config(self):
        config = self.get_config()
        name = self.monitor_data['name']
        
        cmd = ['swaymsg', 'output', name]

        print(f"Applying configuration for {name}: {config}")
        
        if config['enabled']:
            width, height = config['resolution'].split('x')
            x, y = config['position'].split(',')
            
            cmd.extend(['pos', x, y])
            cmd.extend(['res', width, height])
            cmd.extend(['scale', str(config['scale'])])
            cmd.extend(['transform', config['transform']])
        else:
            cmd.append('disable')

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error applying configuration: {e}") 

    def on_transform_changed(self, combo):
        # Update preview when transform changes
        parent = self.get_parent()
        if parent:
            window = parent.get_parent().get_parent()
            if isinstance(window, SwayMonitorWindow):
                window.preview_area.queue_draw()

if __name__ == '__main__':
    app = SwayMonitorManager()
    app.run(None) 