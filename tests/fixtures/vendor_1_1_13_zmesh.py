# Unmodified ZMesh and math helpers extracted from retained WM 1.1.13 bed_mesh.py.
# Mesh Bed Leveling
#
# Copyright (C) 2018-2019 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math, json, collections


PROFILE_VERSION = 1
PROFILE_OPTIONS = {
    'min_x': float, 'max_x': float, 'min_y': float, 'max_y': float,
    'x_count': int, 'y_count': int, 'mesh_x_pps': int, 'mesh_y_pps': int,
    'algo': str, 'tension': float
}

class BedMeshError(Exception):
    pass

# PEP 485 isclose()
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

# return true if a coordinate is within the region
# specified by min_c and max_c
def within(coord, min_c, max_c, tol=0.0):
    return (max_c[0] + tol) >= coord[0] >= (min_c[0] - tol) and \
        (max_c[1] + tol) >= coord[1] >= (min_c[1] - tol)

# Constrain value between min and max
def constrain(val, min_val, max_val):
    return min(max_val, max(min_val, val))

# Linear interpolation between two values
def lerp(t, v0, v1):
    return (1. - t) * v0 + t * v1

# retreive commma separated pair from config
def parse_config_pair(config, option, default, minval=None, maxval=None):
    pair = config.getintlist(option, (default, default))
    if len(pair) != 2:
        if len(pair) != 1:
            raise config.error("bed_mesh: malformed '%s' value: %s"
                               % (option, config.get(option)))
        pair = (pair[0], pair[0])
    if minval is not None:
        if pair[0] < minval or pair[1] < minval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a minimum of %s"
                % (option, str(minval)))
    if maxval is not None:
        if pair[0] > maxval or pair[1] > maxval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a maximum of %s"
                % (option, str(maxval)))
    return pair

# retreive commma separated pair from a g-code command
def parse_gcmd_pair(gcmd, name, minval=None, maxval=None):
    try:
        pair = [int(v.strip()) for v in gcmd.get(name).split(',')]
    except:
        raise gcmd.error("Unable to parse parameter '%s'" % (name,))
    if len(pair) != 2:
        if len(pair) != 1:
            raise gcmd.error("Unable to parse parameter '%s'" % (name,))
        pair = (pair[0], pair[0])
    if minval is not None:
        if pair[0] < minval or pair[1] < minval:
            raise gcmd.error("Parameter '%s' must have a minimum of %d"
                             % (name, minval))
    if maxval is not None:
        if pair[0] > maxval or pair[1] > maxval:
            raise gcmd.error("Parameter '%s' must have a maximum of %d"
                             % (name, maxval))
    return pair

# retreive commma separated coordinate from a g-code command
def parse_gcmd_coord(gcmd, name):
    try:
        v1, v2 = [float(v.strip()) for v in gcmd.get(name).split(',')]
    except:
        raise gcmd.error("Unable to parse parameter '%s'" % (name,))
    return v1, v2


class ZMesh:
    def __init__(self, params, name):
        self.profile_name = name or "adaptive-%X" % (id(self),)
        self.probed_matrix = self.mesh_matrix = None
        self.mesh_params = params
        self.mesh_offsets = [0., 0.]
        logging.debug('bed_mesh: probe/mesh parameters:')
        for key, value in self.mesh_params.items():
            logging.debug("%s :  %s" % (key, value))
        self.mesh_x_min = params['min_x']
        self.mesh_x_max = params['max_x']
        self.mesh_y_min = params['min_y']
        self.mesh_y_max = params['max_y']
        logging.debug(
            "bed_mesh: Mesh Min: (%.2f,%.2f) Mesh Max: (%.2f,%.2f)"
            % (self.mesh_x_min, self.mesh_y_min,
               self.mesh_x_max, self.mesh_y_max))
        # Set the interpolation algorithm
        interpolation_algos = {
            'lagrange': self._sample_lagrange,
            'bicubic': self._sample_bicubic,
            'direct': self._sample_direct
        }
        self._sample = interpolation_algos.get(params['algo'])
        # Number of points to interpolate per segment
        mesh_x_pps = params['mesh_x_pps']
        mesh_y_pps = params['mesh_y_pps']
        px_cnt = params['x_count']
        py_cnt = params['y_count']
        self.mesh_x_count = (px_cnt - 1) * mesh_x_pps + px_cnt
        self.mesh_y_count = (py_cnt - 1) * mesh_y_pps + py_cnt
        self.x_mult = mesh_x_pps + 1
        self.y_mult = mesh_y_pps + 1
        logging.debug("bed_mesh: Mesh grid size - X:%d, Y:%d"
                      % (self.mesh_x_count, self.mesh_y_count))
        self.mesh_x_dist = (self.mesh_x_max - self.mesh_x_min) / \
                           (self.mesh_x_count - 1)
        self.mesh_y_dist = (self.mesh_y_max - self.mesh_y_min) / \
                           (self.mesh_y_count - 1)
    def get_mesh_matrix(self):
        if self.mesh_matrix is not None:
            return [[round(z, 6) for z in line]
                    for line in self.mesh_matrix]
        return [[]]
    def get_probed_matrix(self):
        if self.probed_matrix is not None:
            return [[round(z, 6) for z in line]
                    for line in self.probed_matrix]
        return [[]]
    def get_mesh_params(self):
        return self.mesh_params
    def get_profile_name(self):
        return self.profile_name
    def print_probed_matrix(self, print_func):
        if self.probed_matrix is not None:
            msg = "Mesh Leveling Probed Z positions:\n"
            for line in self.probed_matrix:
                for x in line:
                    msg += " %f" % x
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: bed has not been probed")
    def print_mesh(self, print_func, move_z=None):
        matrix = self.get_mesh_matrix()
        if matrix is not None:
            msg = "Mesh X,Y: %d,%d\n" % (self.mesh_x_count, self.mesh_y_count)
            if move_z is not None:
                msg += "Search Height: %d\n" % (move_z)
            msg += "Mesh Offsets: X=%.4f, Y=%.4f\n" % (
                self.mesh_offsets[0], self.mesh_offsets[1])
            msg += "Mesh Average: %.2f\n" % (self.get_z_average())
            rng = self.get_z_range()
            msg += "Mesh Range: min=%.4f max=%.4f\n" % (rng[0], rng[1])
            msg += "Interpolation Algorithm: %s\n" \
                   % (self.mesh_params['algo'])
            msg += "Measured points:\n"
            for y_line in range(self.mesh_y_count - 1, -1, -1):
                for z in matrix[y_line]:
                    msg += "  %f" % (z)
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: Z Mesh not generated")
    def build_mesh(self, z_matrix):
        self.probed_matrix = z_matrix
        self._sample(z_matrix)
        self.print_mesh(logging.debug)
    def set_zero_reference(self, xpos, ypos):
        offset = self.calc_z(xpos, ypos)
        logging.info(
            "bed_mesh: setting zero reference at (%.2f, %.2f, %.6f)"
            % (xpos, ypos, offset)
        )
        for matrix in [self.probed_matrix, self.mesh_matrix]:
            for yidx in range(len(matrix)):
                for xidx in range(len(matrix[yidx])):
                    matrix[yidx][xidx] -= offset
    def set_mesh_offsets(self, offsets):
        for i, o in enumerate(offsets):
            if o is not None:
                self.mesh_offsets[i] = o
    def get_x_coordinate(self, index):
        return self.mesh_x_min + self.mesh_x_dist * index
    def get_y_coordinate(self, index):
        return self.mesh_y_min + self.mesh_y_dist * index
    def calc_z(self, x, y):
        if self.mesh_matrix is not None:
            tbl = self.mesh_matrix
            tx, xidx = self._get_linear_index(x + self.mesh_offsets[0], 0)
            ty, yidx = self._get_linear_index(y + self.mesh_offsets[1], 1)
            z0 = lerp(tx, tbl[yidx][xidx], tbl[yidx][xidx+1])
            z1 = lerp(tx, tbl[yidx+1][xidx], tbl[yidx+1][xidx+1])
            return lerp(ty, z0, z1)
        else:
            # No mesh table generated, no z-adjustment
            return 0.
    def get_z_range(self):
        if self.mesh_matrix is not None:
            mesh_min = min([min(x) for x in self.mesh_matrix])
            mesh_max = max([max(x) for x in self.mesh_matrix])
            return mesh_min, mesh_max
        else:
            return 0., 0.
    def get_z_average(self):
        if self.mesh_matrix is not None:
            avg_z = (sum([sum(x) for x in self.mesh_matrix]) /
                     sum([len(x) for x in self.mesh_matrix]))
            # Round average to the nearest 100th.  This
            # should produce an offset that is divisible by common
            # z step distances
            return round(avg_z, 2)
        else:
            return 0.
    def _get_linear_index(self, coord, axis):
        if axis == 0:
            # X-axis
            mesh_min = self.mesh_x_min
            mesh_cnt = self.mesh_x_count
            mesh_dist = self.mesh_x_dist
            cfunc = self.get_x_coordinate
        else:
            # Y-axis
            mesh_min = self.mesh_y_min
            mesh_cnt = self.mesh_y_count
            mesh_dist = self.mesh_y_dist
            cfunc = self.get_y_coordinate
        t = 0.
        idx = int(math.floor((coord - mesh_min) / mesh_dist))
        idx = constrain(idx, 0, mesh_cnt - 2)
        t = (coord - cfunc(idx)) / mesh_dist
        return constrain(t, 0., 1.), idx
    def _sample_direct(self, z_matrix):
        self.mesh_matrix = z_matrix
    def _sample_lagrange(self, z_matrix):
        x_mult = self.x_mult
        y_mult = self.y_mult
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j//y_mult][i//x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        xpts, ypts = self._get_lagrange_coords()
        # Interpolate X coordinates
        for i in range(self.mesh_y_count):
            # only interpolate X-rows that have probed coordinates
            if i % y_mult != 0:
                continue
            for j in range(self.mesh_x_count):
                if j % x_mult == 0:
                    continue
                x = self.get_x_coordinate(j)
                self.mesh_matrix[i][j] = self._calc_lagrange(xpts, x, i, 0)
        # Interpolate Y coordinates
        for i in range(self.mesh_x_count):
            for j in range(self.mesh_y_count):
                if j % y_mult == 0:
                    continue
                y = self.get_y_coordinate(j)
                self.mesh_matrix[j][i] = self._calc_lagrange(ypts, y, i, 1)
    def _get_lagrange_coords(self):
        xpts = []
        ypts = []
        for i in range(self.mesh_params['x_count']):
            xpts.append(self.get_x_coordinate(i * self.x_mult))
        for j in range(self.mesh_params['y_count']):
            ypts.append(self.get_y_coordinate(j * self.y_mult))
        return xpts, ypts
    def _calc_lagrange(self, lpts, c, vec, axis=0):
        pt_cnt = len(lpts)
        total = 0.
        for i in range(pt_cnt):
            n = 1.
            d = 1.
            for j in range(pt_cnt):
                if j == i:
                    continue
                n *= (c - lpts[j])
                d *= (lpts[i] - lpts[j])
            if axis == 0:
                # Calc X-Axis
                z = self.mesh_matrix[vec][i*self.x_mult]
            else:
                # Calc Y-Axis
                z = self.mesh_matrix[i*self.y_mult][vec]
            total += z * n / d
        return total
    def _sample_bicubic(self, z_matrix):
        # should work for any number of probe points above 3x3
        x_mult = self.x_mult
        y_mult = self.y_mult
        c = self.mesh_params['tension']
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j//y_mult][i//x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        # Interpolate X values
        for y in range(self.mesh_y_count):
            if y % y_mult != 0:
                continue
            for x in range(self.mesh_x_count):
                if x % x_mult == 0:
                    continue
                pts = self._get_x_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
        # Interpolate Y values
        for x in range(self.mesh_x_count):
            for y in range(self.mesh_y_count):
                if y % y_mult == 0:
                    continue
                pts = self._get_y_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
    def _get_x_ctl_pts(self, x, y):
        # Fetch control points and t for a X value in the mesh
        x_mult = self.x_mult
        x_row = self.mesh_matrix[y]
        last_pt = self.mesh_x_count - 1 - x_mult
        if x < x_mult:
            p0 = p1 = x_row[0]
            p2 = x_row[x_mult]
            p3 = x_row[2*x_mult]
            t = x / float(x_mult)
        elif x > last_pt:
            p0 = x_row[last_pt - x_mult]
            p1 = x_row[last_pt]
            p2 = p3 = x_row[last_pt + x_mult]
            t = (x - last_pt) / float(x_mult)
        else:
            found = False
            for i in range(x_mult, last_pt, x_mult):
                if x > i and x < (i + x_mult):
                    p0 = x_row[i - x_mult]
                    p1 = x_row[i]
                    p2 = x_row[i + x_mult]
                    p3 = x_row[i + 2*x_mult]
                    t = (x - i) / float(x_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding x control points")
        return p0, p1, p2, p3, t
    def _get_y_ctl_pts(self, x, y):
        # Fetch control points and t for a Y value in the mesh
        y_mult = self.y_mult
        last_pt = self.mesh_y_count - 1 - y_mult
        y_col = self.mesh_matrix
        if y < y_mult:
            p0 = p1 = y_col[0][x]
            p2 = y_col[y_mult][x]
            p3 = y_col[2*y_mult][x]
            t = y / float(y_mult)
        elif y > last_pt:
            p0 = y_col[last_pt - y_mult][x]
            p1 = y_col[last_pt][x]
            p2 = p3 = y_col[last_pt + y_mult][x]
            t = (y - last_pt) / float(y_mult)
        else:
            found = False
            for i in range(y_mult, last_pt, y_mult):
                if y > i and y < (i + y_mult):
                    p0 = y_col[i - y_mult][x]
                    p1 = y_col[i][x]
                    p2 = y_col[i + y_mult][x]
                    p3 = y_col[i + 2*y_mult][x]
                    t = (y - i) / float(y_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding y control points")
        return p0, p1, p2, p3, t
    def _cardinal_spline(self, p, tension):
        t = p[4]
        t2 = t*t
        t3 = t2*t
        m1 = tension * (p[2] - p[0])
        m2 = tension * (p[3] - p[1])
        a = p[1] * (2*t3 - 3*t2 + 1)
        b = p[2] * (-2*t3 + 3*t2)
        c = m1 * (t3 - 2*t2 + t)
        d = m2 * (t3 - t2)
        return a + b + c + d


