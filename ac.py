import json, sys, csv
from math import radians, cos, sin, sqrt, atan2, degrees

FILE = 'acrace.json'
PORT = 0
STARBOARD = 1
R = 6371.0  # Radius of Earth in kilometers
MS_TO_KN = 1.943844

class Boat:
    def __init__(self, asset, axis):
        self.id = asset["id"]
        self.name = asset["abbreviation"]
        self.events = []
        self.next = -1
        self.last_timestamp = 0
        self.lat = self.lon = None
        self.axis = axis
        self.twd = self.twa = self.tws = self.hdg = self.cog = self.chdg = self.spd = self.cspd = self.vmg = self.cdst = None
        self.writer = None
        self.start_time = None


    def __str__(self):
        return json.dumps({"name": self.name, "id": self.id, "Speed": self.spd, "C_Speed": self.cspd, "HDG": self.hdg, "TWD": self.twd, "TWS": self.tws}, indent=2)

    def init_vars(self, start_time):
        self.start_time = start_time
        while (self.twd == None or self.tws == None or self.hdg == None or self.cog == None or self.spd == None or self.lat == None or self.chdg == None or self.twa == None or self.vmg == None):
            self.process_event()

    def params(self):
        return {"Speed": self.spd, "C_Speed": self.cspd, "TWD": self.twd, "HDG": self.hdg, "TWA": self.twa, "C_HDG": self.chdg, "C_DST": self.cdst,  "TWS": self.tws, "VMG": self.vmg}

    def process_event(self):
        if self._exit_if_events_finished():
            return False
        event_data = self.events[self.next]
        old_hdg, old_twd, old_lat, old_lon = self.hdg, self.twd, self.lat, self.lon
        if "course_over_ground" in event_data:
            self.cog = event_data["course_over_ground"]["value"]
            self.calculate_vmg()
        elif "heading" in event_data:
            self.hdg = event_data["heading"]["value"]
            self.calculate_twa()
        elif "true_wind_direction" in event_data:
            self.twd = event_data["true_wind_direction"]["value"]
            self.calculate_twa()
        elif "true_wind_speed" in event_data:
            self.tws = MS_TO_KN*event_data["true_wind_speed"]["value"]
        elif "speed_over_ground" in event_data:
            self.spd = MS_TO_KN*event_data["speed_over_ground"]["value"]
            self.calculate_vmg()
        elif "gnss_position" in event_data:
            self.lat, self.lon = event_data["gnss_position"]["latitude"], event_data["gnss_position"]["longitude"]
            if old_lat is not None:
                self.chdg = self.calculate_heading(old_lat, old_lon)
                self.cspd = self.calculate_speed(old_lat, old_lon, int(event_data["timestamp"]), self.last_timestamp)
        self.last_timestamp = int(event_data["timestamp"])
        self.next = self.next + 1
        return True

    def haversine_distance(self, old_lat, old_lon):
        lat1, lon1 = radians(old_lat), radians(old_lon)
        lat2, lon2 = radians(self.lat), radians(self.lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = R * c
        return distance

    def calculate_heading(self, old_lat, old_lon):
        lat1, lon1 = radians(old_lat), radians(old_lon)
        lat2, lon2 = radians(self.lat), radians(self.lon)

        dlon = lon2 - lon1

        x = sin(dlon) * cos(lat2)
        y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)

        initial_heading = atan2(x, y)

        # Convert from radians to degrees and normalize to 0-360
        initial_heading = degrees(initial_heading)
        heading = (initial_heading + 360) % 360

        return heading

    def calculate_speed(self, old_lat, old_lon, timestamp, old_timestamp):
        if old_lat is None or old_lon is None:
            return
        self.cdst = 1000*self.haversine_distance(old_lat, old_lon)  # m

        time_diff_milliseconds = timestamp - old_timestamp
        if time_diff_milliseconds == 0:
            return 0

        speed_mh = (self.cdst / time_diff_milliseconds) * 1000  # m/s
        return speed_mh * 1.943844  # kn

    def calculate_twa(self):
        if self.twd is None or self.hdg is None:
            return
        twa = self.twd - self.hdg
        if abs(twa) >= 180:
            twa = 360 - abs(twa)
        self.twa = twa

    def calculate_vmg(self):
        if self.cog is None or self.spd is None:
            return
        angle = radians(self.axis - self.cog)
        self.vmg = self.spd * abs(cos(angle))

    def update_axis(self, axis):
        self.axis = axis

    def _exit_if_events_finished(self):
        if self.next >= len(self.events) - 1:
            return True
        return False

    def write_data_row(self):
        if self.writer is None:
            quit("No CSV writer provided.")
        self.writer.writerow([
            self.last_timestamp - self.start_time, round(self.hdg, 1), round(self.cog, 1), round(self.spd, 2), round(self.vmg, 2), round(self.twa, 1), round(self.twd, 1), round(self.tws, 2),
        ])


class RaceObserver:
    def __init__(self, data, race_name):
        self.data = data[2:]
        self.metadata = data[0]
        self._metadata = data[1]
        self.race_name = race_name
        self.start_time = int(self.metadata["session"]["race_start"])
        self.axis = self.metadata["session"]["race_course"]["course_axis"]
        self.axis_events = []
        self.next_axis_event = 0
        self._find_competitors()
        self._init_events()
        self.port.init_vars(self.start_time)
        self.starboard.init_vars(self.start_time)
        self.last_timestamp = max(self.port.last_timestamp, self.starboard.last_timestamp)


    def __str__(self):
        return "%s: %s\n%s: %s" % (self.port.name, self.port.id, self.starboard.name, self.starboard.id)

    def _find_competitors(self):
        competitors = self.metadata["session"]["competitors"]
        if competitors[PORT]["start_entry"] != "START_ENTRY_PORT":
           competitors[PORT], competitors[STARBOARD] = competitors[STARBOARD], competitors[PORT]
        for asset in self.metadata["session"]["assets"]:
            if asset["id"] == competitors[PORT]["asset_id"]:
                self.port = Boat(asset, self.axis)
            if asset["id"] == competitors[STARBOARD]["asset_id"]:
                self.starboard = Boat(asset, self.axis)

    # only use after running _find_competitors()
    def _init_events(self):
        for event in self.data:
            if "telemetry" in event:
                if event["telemetry"]["asset_id"] == self.port.id:
                    self.port.events.append(event["telemetry"])
                if event["telemetry"]["asset_id"] == self.starboard.id:
                    self.starboard.events.append(event["telemetry"])
            elif "session" in event:
                self.axis_events.append((event["session"]["race_course"]["course_axis"], int(event["session"]["timestamp"])))


    def _time_of_race(self, timestamp):
        diff = int(timestamp) - self.start_time
        minutes, seconds = divmod(abs(diff)/1000, 60)
        prefix = ""
        if diff < 0:
             prefix = "-"
        return prefix + f"{int(minutes)}:{int(seconds):02d}"

    def _print_state(self):
            print(f"{self._time_of_race(self.last_timestamp)}")
            for boat in [self.port, self.starboard]:
                print(f"\t{boat.name}:")
                params = boat.params()
                for key in params:
                    print(f"\t\t{key}: {params[key]}")

    def _sim_step(self, step):
        self.last_timestamp = self.last_timestamp + step
        if self.next_axis_event < len(self.axis_events):
            (axis, timestamp) = self.axis_events[self.next_axis_event]
            if timestamp <= self.last_timestamp:
                self.axis = self.port.axis = self.starboard.axis = axis
                self.next_axis_event = self.next_axis_event + 1
        for boat in [self.port, self.starboard]:
            while boat.last_timestamp <= self.last_timestamp and not boat._exit_if_events_finished():
                boat.process_event()

    def _all_events_not_finished(self):
        return not (self.port._exit_if_events_finished() and self.starboard._exit_if_events_finished())

    def simulate_and_print(self, step=200):
        while self._all_events_not_finished():
            self._sim_step(step)
            self._print_state()

    def export_race_to_csv(self, step=200):
        with open(f"{self.race_name}_port_{self.port.name}.csv", mode='w', newline='') as port_file:
            with open(f"{self.race_name}_starboard_{self.starboard.name}.csv", mode='w', newline='') as starboard_file:
                self.port.writer, self.starboard.writer = csv.writer(port_file), csv.writer(starboard_file)
                for boat in [self.port, self.starboard]:
                    boat.writer.writerow(['Timestamp', 'HDG', 'COG', 'SPD', 'VMG', 'TWA', 'TWD', 'TWS'])
                while self._all_events_not_finished():
                    self._sim_step(step)
                    for boat in [self.port, self.starboard]:
                         boat.write_data_row()


if __name__ == "__main__":
    if len(sys.argv) <= 1:
        quit("Error, no file given. The file name argument is required.")

    with open(sys.argv[1], 'r') as f:
        data = [json.loads(line) for line in f]
        
    # Assuming the input file has an extension
    ro = RaceObserver(data, sys.argv[1].split('.')[0])
    print(ro.port)
    print(ro.starboard)
    ro.export_race_to_csv(step=200)
