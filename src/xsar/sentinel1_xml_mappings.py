"""
xpath mapping from xml file, with convertion functions
"""

from datetime import datetime
import numpy as np
from scipy.interpolate import RectBivariateSpline, interp1d
from numpy.polynomial import Polynomial
from shapely.geometry import box
import pandas as pd
import xarray as xr
import warnings
import geopandas as gpd
from shapely.geometry import Polygon
import os.path
import logging
import netCDF4

logger = logging.getLogger('xsar.sentinel1_xml_mappings')
logger.addHandler(logging.NullHandler())

namespaces = {
    "xfdu": "urn:ccsds:schema:xfdu:1",
    "s1sarl1": "http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar/level-1",
    "s1sar": "http://www.esa.int/safe/sentinel-1.0/sentinel-1/sar",
    "s1": "http://www.esa.int/safe/sentinel-1.0/sentinel-1",
    "safe": "http://www.esa.int/safe/sentinel-1.0",
    "gml": "http://www.opengis.net/gml"
}
TIMEUNITS = 'seconds since 1990-01-01T00:00:00'
# xpath convertion function: they take only one args (list returned by xpath)
scalar = lambda x: x[0]
scalar_int = lambda x: int(x[0])
scalar_float = lambda x: float(x[0])
date_converter = lambda x: datetime.strptime(x[0], '%Y-%m-%dT%H:%M:%S.%f')
datetime64_array = lambda x: np.array([np.datetime64(date_converter([sx])) for sx in x])
datenum_array = lambda x: np.array([netCDF4.date2num(date_converter([sx]),TIMEUNITS) for sx in x])
int_1Darray_from_string = lambda x: np.fromstring(x[0], dtype=int, sep=' ')
float_2Darray_from_string_list = lambda x: np.vstack([np.fromstring(e, dtype=float, sep=' ') for e in x])
int_1Darray_from_join_strings = lambda x: np.fromstring(" ".join(x), dtype=int, sep=' ')
float_1Darray_from_join_strings = lambda x: np.fromstring(" ".join(x), dtype=float, sep=' ')
int_array = lambda x: np.array(x, dtype=int)
bool_array = lambda x: np.array(x, dtype=bool)
float_array = lambda x: np.array(x, dtype=float)
uniq_sorted = lambda x: np.array(sorted(set(x)))
ordered_category = lambda x: pd.Categorical(x).reorder_categories(x, ordered=True)
normpath = lambda paths: [os.path.normpath(p) for p in paths]


def or_ipf28(xpath):
    """change xpath to match ipf <2.8 or >2.9 (for noise range)"""
    xpath28 = xpath.replace('noiseRange', 'noise').replace('noiseAzimuth', 'noise')
    if xpath28 != xpath:
        xpath += " | %s" % xpath28
    return xpath


def list_poly_from_list_string_coords(str_coords_list):
    footprints = []
    for gmlpoly in str_coords_list:
        footprints.append(Polygon(
            [(float(lon), float(lat)) for lat, lon in [latlon.split(",")
                                                       for latlon in gmlpoly.split(" ")]]))
    return footprints


# xpath_mappings:
# first level key is xml file type
# second level key is variable name
# mappings may be 'xpath', or 'tuple(func,xpath)', or 'dict'
#  - xpath is an lxml xpath
#  - func is a decoder function fed by xpath
#  - dict is a nested dict, to create more hierarchy levels.
xpath_mappings = {
    "manifest": {
        'ipf_version': (scalar_float, '//xmlData/safe:processing/safe:facility/safe:software/@version'),
        'swath_type': (scalar, '//s1sarl1:instrumentMode/s1sarl1:mode'),
        'polarizations': (
            ordered_category, '//s1sarl1:standAloneProductInformation/s1sarl1:transmitterReceiverPolarisation'),
        'footprints': (list_poly_from_list_string_coords, '//safe:frame/safe:footPrint/gml:coordinates'),
        'product_type': (scalar, '//s1sarl1:standAloneProductInformation/s1sarl1:productType'),
        'mission': (scalar, '//safe:platform/safe:familyName'),
        'satellite': (scalar, '//safe:platform/safe:number'),
        'start_date': (date_converter, '//safe:acquisitionPeriod/safe:startTime'),
        'stop_date': (date_converter, '//safe:acquisitionPeriod/safe:stopTime'),
        'annotation_files': (
            normpath, '/xfdu:XFDU/dataObjectSection/*[@repID="s1Level1ProductSchema"]/byteStream/fileLocation/@href'),
        'measurement_files': (
            normpath,
            '/xfdu:XFDU/dataObjectSection/*[@repID="s1Level1MeasurementSchema"]/byteStream/fileLocation/@href'),
        'noise_files': (
            normpath, '/xfdu:XFDU/dataObjectSection/*[@repID="s1Level1NoiseSchema"]/byteStream/fileLocation/@href'),
        'calibration_files': (
            normpath,
            '/xfdu:XFDU/dataObjectSection/*[@repID="s1Level1CalibrationSchema"]/byteStream/fileLocation/@href')
    },
    'calibration': {
        'polarization': (scalar, '/calibration/adsHeader/polarisation'),
        # 'number_of_vector': '//calibration/calibrationVectorList/@count',
        'atrack': (np.array, '//calibration/calibrationVectorList/calibrationVector/line'),
        'xtrack': (int_1Darray_from_string, '//calibration/calibrationVectorList/calibrationVector[1]/pixel'),
        'sigma0_lut': (
            float_2Darray_from_string_list, '//calibration/calibrationVectorList/calibrationVector/sigmaNought'),
        'gamma0_lut': (float_2Darray_from_string_list, '//calibration/calibrationVectorList/calibrationVector/gamma')
    },
    'noise': {
        'polarization': (scalar, '/noise/adsHeader/polarisation'),
        'range': {
            'atrack': (int_array, or_ipf28('/noise/noiseRangeVectorList/noiseRangeVector/line')),
            'xtrack': (lambda x: [np.fromstring(s, dtype=int, sep=' ') for s in x],
                       or_ipf28('/noise/noiseRangeVectorList/noiseRangeVector/pixel')),
            'noiseLut': (
                lambda x: [np.fromstring(s, dtype=float, sep=' ') for s in x],
                or_ipf28('/noise/noiseRangeVectorList/noiseRangeVector/noiseRangeLut'))
        },
        'azi': {
            'swath': '/noise/noiseAzimuthVectorList/noiseAzimuthVector/swath',
            'atrack': (lambda x: [np.fromstring(str(s), dtype=int, sep=' ') for s in x],
                       '/noise/noiseAzimuthVectorList/noiseAzimuthVector/line'),
            'atrack_start': (int_array, '/noise/noiseAzimuthVectorList/noiseAzimuthVector/firstAzimuthLine'),
            'atrack_stop': (int_array, '/noise/noiseAzimuthVectorList/noiseAzimuthVector/lastAzimuthLine'),
            'xtrack_start': (int_array, '/noise/noiseAzimuthVectorList/noiseAzimuthVector/firstRangeSample'),
            'xtrack_stop': (int_array, '/noise/noiseAzimuthVectorList/noiseAzimuthVector/lastRangeSample'),
            'noiseLut': (
                lambda x: [np.fromstring(str(s), dtype=float, sep=' ') for s in x],
                '/noise/noiseAzimuthVectorList/noiseAzimuthVector/noiseAzimuthLut'),
        }
    },
    'annotation': {
        'atrack': (uniq_sorted, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/line'),
        'xtrack': (uniq_sorted, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/pixel'),
        'atrack_grid': (int_array, '//product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/line'),
        'xtrack_grid': (int_array, '//product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/pixel'),
        'incidence': (
            float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/incidenceAngle'),
        'elevation': (
            float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/elevationAngle'),
        'height': (float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/height'),
        'azimuth_time': (
            datenum_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/azimuthTime'),
        'slant_range_time': (
            float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/slantRangeTime'),
        'longitude': (float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/longitude'),
        'latitude': (float_array, '/product/geolocationGrid/geolocationGridPointList/geolocationGridPoint/latitude'),
        'number_pts_geolocation_grid':(scalar_int,'/product/geolocationGrid/geolocationGridPointList/@count'),
        'polarization': (scalar, '/product/adsHeader/polarisation'),
        'atrack_time_range': (
            datetime64_array, '/product/imageAnnotation/imageInformation/*[contains(name(),"LineUtcTime")]'),
        'denoised': (scalar, '/product/imageAnnotation/processingInformation/thermalNoiseCorrectionPerformed'),
        'pol': (scalar, '/product/adsHeader/polarisation'),
        'pass': (scalar, '/product/generalAnnotation/productInformation/pass'),
        'platform_heading': (scalar_float, '/product/generalAnnotation/productInformation/platformHeading'),
        'number_of_bursts': (scalar_int, '/product/swathTiming/burstList/@count'),
        'number_of_lines': (scalar, '/product/imageAnnotation/imageInformation/numberOfLines'),
        'incidence_angle_mid_swath': (scalar, '/product/imageAnnotation/imageInformation/incidenceAngleMidSwath'),
        'number_of_samples': (scalar, '/product/imageAnnotation/imageInformation/numberOfSamples'),
        'lines_per_burst': (scalar, '/product/swathTiming/linesPerBurst'),
        'samples_per_burst': (scalar, '/product/swathTiming/samplesPerBurst'),
        'azimuth_time_interval': (scalar_float, '/product/imageAnnotation/imageInformation/azimuthTimeInterval'),
        'all_bursts': (np.array, '//product/swathTiming/burstList/burst'),
        'burst_azimuthTime': (datenum_array, '//product/swathTiming/burstList/burst/azimuthTime'),
        'burst_azimuthAnxTime': (float_array, '//product/swathTiming/burstList/burst/azimuthAnxTime'),
        'burst_sensingTime': (datenum_array, '//product/swathTiming/burstList/burst/sensingTime'),
        'burst_byteOffset': (np.array, '//product/swathTiming/burstList/burst/byteOffset'),
        'burst_firstValidSample': (
            float_2Darray_from_string_list, '//product/swathTiming/burstList/burst/firstValidSample'),
        'burst_lastValidSample': (
            float_2Darray_from_string_list, '//product/swathTiming/burstList/burst/lastValidSample'),
        'radar_frequency': (scalar_float, '/product/generalAnnotation/productInformation/radarFrequency'),
        'nb_state_vector': (scalar_int, '/product/generalAnnotation/orbitList/@count'),
        'nb_fmrate': (scalar_int, '/product/generalAnnotation/azimuthFmRateList/@count'),
        'fmrate_azimuthtime': (np.array, '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/azimuthTime'),
        'fmrate_t0': (float_array, '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/t0'),
        'fmrate_c0': (np.array, '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/c0'),
        'fmrate_c1': (np.array, '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/c1'),
        'fmrate_c2': (np.array, '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/c2'),
        'fmrate_azimuthFmRatePolynomial': (
            float_2Darray_from_string_list,
            '//product/generalAnnotation/azimuthFmRateList/azimuthFmRate/azimuthFmRatePolynomial'),
        'orbit_time': (datenum_array, '//product/generalAnnotation/orbitList/orbit/time'), # needed as float for interpolation
        'orbit_frame': (np.array, '//product/generalAnnotation/orbitList/orbit/frame'),
        'orbit_pos_x': (float_array, '//product/generalAnnotation/orbitList/orbit/position/x'),
        'orbit_pos_y': (float_array, '//product/generalAnnotation/orbitList/orbit/position/y'),
        'orbit_pos_z': (float_array, '//product/generalAnnotation/orbitList/orbit/position/z'),
        'orbit_vel_x': (float_array, '//product/generalAnnotation/orbitList/orbit/velocity/x'),
        'orbit_vel_y': (float_array, '//product/generalAnnotation/orbitList/orbit/velocity/y'),
        'orbit_vel_z': (float_array, '//product/generalAnnotation/orbitList/orbit/velocity/z'),
        'azimuth_steering_rate': (scalar_float, '/product/generalAnnotation/productInformation/azimuthSteeringRate'),
        'nb_dcestimate': (scalar_int, '/product/dopplerCentroid/dcEstimateList/@count'),
        'nb_geoDcPoly': (
            scalar_int, '/product/dopplerCentroid/dcEstimateList/dcEstimate[1]/geometryDcPolynomial/@count'),
        'nb_dataDcPoly': (scalar_int, '/product/dopplerCentroid/dcEstimateList/dcEstimate[1]/dataDcPolynomial/@count'),
        'nb_fineDce': (scalar_int, '/product/dopplerCentroid/dcEstimateList/dcEstimate[1]/fineDceList/@count'),
        'dc_azimuth_time': (np.array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/azimuthTime'),
        'dc_t0': (np.array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/t0'),
        'dc_geoDcPoly': (
            float_2Darray_from_string_list, '//product/dopplerCentroid/dcEstimateList/dcEstimate/geometryDcPolynomial'),
        'dc_dataDcPoly': (
            float_2Darray_from_string_list, '//product/dopplerCentroid/dcEstimateList/dcEstimate/dataDcPolynomial'),
        'dc_rmserr': (np.array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/dataDcRmsError'),
        'dc_rmserrAboveThres': (
            bool_array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/dataDcRmsErrorAboveThreshold'),
        'dc_azstarttime': (np.array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/fineDceAzimuthStartTime'),
        'dc_azstoptime': (np.array, '//product/dopplerCentroid/dcEstimateList/dcEstimate/fineDceAzimuthStopTime'),
        'dc_slantRangeTime': (
            float_array, '///product/dopplerCentroid/dcEstimateList/dcEstimate/fineDceList/fineDce/slantRangeTime'),
        'dc_frequency': (
            float_array, '///product/dopplerCentroid/dcEstimateList/dcEstimate/fineDceList/fineDce/frequency'),
        'range_sampling_rate': (scalar_float, '/product/generalAnnotation/productInformation/rangeSamplingRate'),
        'slant_range_time_image': (scalar_float, '/product/imageAnnotation/imageInformation/slantRangeTime'),
        'rangePixelSpacing': (scalar_float, '/product/imageAnnotation/imageInformation/rangePixelSpacing'),
        'azimuthPixelSpacing': (scalar_float, '/product/imageAnnotation/imageInformation/azimuthPixelSpacing'),

    }
}


# compounds variables converters

def signal_lut(atrack, xtrack, lut):
    logger.debug('signal lut on atrack %s xtrack %s lut : %s', atrack.shape, xtrack.shape, lut.shape)
    lut_f = RectBivariateSpline(atrack, xtrack, lut, kx=1, ky=1)
    return lut_f


class _NoiseLut:
    """small internal class that return a lut function(atracks, xtracks) defined on all the image, from blocks in the image"""

    def __init__(self, blocks):
        self.blocks = blocks

    def __call__(self, atracks, xtracks):
        """ return noise[a.size,x.size], by finding the intersection with blocks and calling the corresponding block.lut_f"""
        if len(self.blocks) == 0:
            # no noise (ie no azi noise for ipf < 2.9)
            return 1
        else:
            # the array to be returned
            noise = xr.DataArray(
                np.ones((atracks.size, xtracks.size)) * np.nan,
                dims=('atrack', 'xtrack'),
                coords={'atrack': atracks, 'xtrack': xtracks}
            )
            # find blocks that intersects with asked_box
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # the box coordinates of the returned array
                asked_box = box(max(0, atracks[0] - 0.5), max(0, xtracks[0] - 0.5), atracks[-1] + 0.5,
                                xtracks[-1] + 0.5)
                # set match_blocks as the non empty intersection with asked_box
                match_blocks = self.blocks.copy()
                match_blocks.geometry = self.blocks.geometry.intersection(asked_box)
                match_blocks = match_blocks[~match_blocks.is_empty]
            for i, block in match_blocks.iterrows():
                (sub_a_min, sub_x_min, sub_a_max, sub_x_max) = map(int, block.geometry.bounds)
                sub_a = atracks[(atracks >= sub_a_min) & (atracks <= sub_a_max)]
                sub_x = xtracks[(xtracks >= sub_x_min) & (xtracks <= sub_x_max)]
                noise.loc[dict(atrack=sub_a, xtrack=sub_x)] = block.lut_f(sub_a, sub_x)

        # values returned as np array
        return noise.values


def noise_lut_range(atracks, xtracks, noiseLuts):
    """

    Parameters
    ----------
    atracks: np.ndarray
        1D array of atracks. lut is defined at each atrack
    xtracks: list of np.ndarray
        arrays of xtracks. list length is same as xtracks. each array define xtracks where lut is defined
    noiseLuts: list of np.ndarray
        arrays of luts. Same structure as xtracks.

    Returns
    -------
    geopandas.GeoDataframe
        noise range geometry.
        'geometry' is the polygon where 'lut_f' is defined.
        attrs['type'] set to 'xtrack'


    """

    class Lut_box_range:
        def __init__(self, a_start, a_stop, x, l):
            self.atracks = np.arange(a_start, a_stop)
            self.xtracks = x
            self.area = box(a_start, x[0], a_stop, x[-1])
            self.lut_f = interp1d(x, l, kind='linear', fill_value=np.nan, assume_sorted=True, bounds_error=False)

        def __call__(self, atracks, xtracks):
            lut = np.tile(self.lut_f(xtracks), (atracks.size, 1))
            return lut

    blocks = []
    # atracks is where lut is defined. compute atracks interval validity
    atracks_start = (atracks - np.diff(atracks, prepend=0) / 2).astype(int)
    atracks_stop = np.ceil(
        atracks + np.diff(atracks, append=atracks[-1] + 1) / 2
    ).astype(int)  # end is not included in the interval
    atracks_stop[-1] = 65535  # be sure to include all image if last azimuth line, is not last azimuth image
    for a_start, a_stop, x, l in zip(atracks_start, atracks_stop, xtracks, noiseLuts):
        lut_f = Lut_box_range(a_start, a_stop, x, l)
        block = pd.Series(dict([
            ('lut_f', lut_f),
            ('geometry', lut_f.area)]))
        blocks.append(block)

    # to geopandas
    blocks = pd.concat(blocks, axis=1).T
    blocks = gpd.GeoDataFrame(blocks)

    return _NoiseLut(blocks)


def noise_lut_azi(atrack_azi, atrack_azi_start,
                  atrack_azi_stop,
                  xtrack_azi_start, xtrack_azi_stop, noise_azi_lut, swath):
    """

    Parameters
    ----------
    atrack_azi
    atrack_azi_start
    atrack_azi_stop
    xtrack_azi_start
    xtrack_azi_stop
    noise_azi_lut
    swath

    Returns
    -------
    geopandas.GeoDataframe
        noise range geometry.
        'geometry' is the polygon where 'lut_f' is defined.
        attrs['type'] set to 'atrack'
    """

    class Lut_box_azi:
        def __init__(self, sw, a, a_start, a_stop, x_start, x_stop, lut):
            self.atracks = a
            self.xtracks = np.arange(x_start, x_stop + 1)
            self.area = box(max(0, a_start - 0.5), max(0, x_start - 0.5), a_stop + 0.5, x_stop + 0.5)
            if len(lut) > 1:
                self.lut_f = interp1d(a, lut, kind='linear', fill_value='extrapolate', assume_sorted=True,
                                      bounds_error=False)
            else:
                # not enought values to do interpolation
                # noise will be constant on this box!
                self.lut_f = lambda _a: lut

        def __call__(self, atracks, xtracks):
            return np.tile(self.lut_f(atracks), (xtracks.size, 1)).T

    blocks = []
    for sw, a, a_start, a_stop, x_start, x_stop, lut in zip(swath, atrack_azi, atrack_azi_start, atrack_azi_stop,
                                                            xtrack_azi_start,
                                                            xtrack_azi_stop, noise_azi_lut):
        lut_f = Lut_box_azi(sw, a, a_start, a_stop, x_start, x_stop, lut)
        block = pd.Series(dict([
            ('lut_f', lut_f),
            ('geometry', lut_f.area)]))
        blocks.append(block)

    if len(blocks) == 0:
        # no azi noise (ipf < 2.9) or WV
        blocks.append(pd.Series(dict([
            ('atracks', np.array([])),
            ('xtracks', np.array([])),
            ('lut_f', lambda a, x: 1),
            ('geometry', box(0, 0, 65535, 65535))])))  # arbitrary large box (bigger than whole image)

    # to geopandas
    blocks = pd.concat(blocks, axis=1).T
    blocks = gpd.GeoDataFrame(blocks)

    return _NoiseLut(blocks)


def annotation_angle(atrack, xtrack, angle):
    lut = angle.reshape(atrack.size, xtrack.size)
    lut_f = RectBivariateSpline(atrack, xtrack, lut, kx=1, ky=1)
    return lut_f


def datetime64_array(dates):
    """list of datetime to np.datetime64 array"""
    return np.array([np.datetime64(d) for d in dates])


def df_files(annotation_files, measurement_files, noise_files, calibration_files):
    # get polarizations and file number from filename
    pols = [os.path.basename(f).split('-')[3].upper() for f in annotation_files]
    num = [int(os.path.splitext(os.path.basename(f))[0].split('-')[8]) for f in annotation_files]
    dsid = [os.path.basename(f).split('-')[1].upper() for f in annotation_files]

    # check that dsid are spatialy uniques (i.e. there is only one dsid per geographic position)
    # some SAFES like WV, dsid are not uniques ('WV1' and 'WV2')
    # we want them uniques, and compatibles with gdal sentinel driver (ie 'WV_012')
    pols_count = len(set(pols))
    subds_count = len(annotation_files) // pols_count
    dsid_count = len(set(dsid))
    if dsid_count != subds_count:
        dsid_rad = dsid[0][:-1]  # WV
        dsid = ["%s_%03d" % (dsid_rad, n) for n in num]
        assert len(set(dsid)) == subds_count  # probably an unknown mode we need to handle

    df = pd.DataFrame(
        {
            'polarization': pols,
            'dsid': dsid,
            'annotation': annotation_files,
            'measurement': measurement_files,
            'noise': noise_files,
            'calibration': calibration_files
        },
        index=num
    )
    return df

def geolocation_grid(atrack, xtrack, values):
    """

    Parameters
    ----------
    atrack: np.ndarray
        1D array of atrack dimension
    xtrack: np.ndarray

    Returns
    -------
    xarray.DataArray
        with atrack and xtrack coordinates, and values as 2D

    """
    shape = (atrack.size, xtrack.size)
    values = np.reshape(values, shape)
    return xr.DataArray(values, dims=['atrack', 'xtrack'], coords={'atrack': atrack, 'xtrack': xtrack})


def bursts(lines_per_burst, samples_per_burst, burst_azimuthTime, burst_azimuthAnxTime, burst_sensingTime,
           burst_byteOffset, burst_firstValidSample, burst_lastValidSample):
    """return burst as an xarray dataset"""

    if (lines_per_burst == 0) and (samples_per_burst == 0):
        return None

    # convert to float, so we can use NaN as missing value, instead of -1
    burst_firstValidSample = burst_firstValidSample.astype(float)
    burst_lastValidSample = burst_lastValidSample.astype(float)
    burst_firstValidSample[burst_firstValidSample == -1] = np.nan
    burst_lastValidSample[burst_lastValidSample == -1] = np.nan
    nbursts = len(burst_azimuthTime)
    valid_locations = np.empty((nbursts, 4), dtype='int32')
    for ibur in range(nbursts):
        fvs = burst_firstValidSample[ibur, :]
        lvs = burst_lastValidSample[ibur, :]
        #valind = np.where((fvs != -1) | (lvs != -1))[0]
        valind = np.where(np.isfinite(fvs) | np.isfinite(lvs))[0]
        valloc = [ibur * lines_per_burst + valind.min(), fvs[valind].min(),
                  ibur * lines_per_burst + valind.max(), lvs[valind].max()]
        valid_locations[ibur, :] = valloc
    da = xr.Dataset(
        {
            'azimuthTime': ('burst', burst_azimuthTime),
            'azimuthAnxTime': ('burst', burst_azimuthAnxTime),
            'sensingTime': ('burst', burst_sensingTime),
            'byteOffset': ('burst', burst_byteOffset),
            'firstValidSample': (['burst', 'xtrack'], burst_firstValidSample),
            'lastValidSample': (['burst', 'xtrack'], burst_lastValidSample),
            'valid_location': xr.DataArray(dims=['burst', 'limits'], data=valid_locations,
                                           attrs={
                                               'description': 'start atrack index, start xtrack index, stop atrack index, stop xtrack index'}),
        }
    )
    da.attrs = {'lines_per_burst':lines_per_burst}
    return da

def orbit(time, frame, pos_x, pos_y, pos_z, vel_x, vel_y, vel_z,orbit_pass,platform_heading):
    """
    return orbit vectors during acquisition (position and velocity)
    Returns
    -------
    xarray.DataArray
        with time and xyz coordinates, and values as 1D and 2D

    """
    da = xr.Dataset()
    da['frame'] = xr.DataArray(frame,dims=['time'],coords={'time':time})
    da['pos_x'] = xr.DataArray(pos_x, dims=['time'], coords={'time': time})
    da['pos_y'] = xr.DataArray(pos_y, dims=['time'], coords={'time': time})
    da['pos_z'] = xr.DataArray(pos_z, dims=['time'], coords={'time': time})
    da['vel_x'] = xr.DataArray(vel_x, dims=['time'], coords={'time': time})
    da['vel_y'] = xr.DataArray(vel_y, dims=['time'], coords={'time': time})
    da['vel_z'] = xr.DataArray(vel_z, dims=['time'], coords={'time': time})
    da['velocity'] = xr.DataArray(np.vstack([vel_x,vel_y,vel_z]).T,dims=['time','xyz'],
                                  coords={'time': time,'xyz':np.arange(3)})
    da['position'] = xr.DataArray(np.vstack([pos_x, pos_y, pos_z]).T, dims=['time', 'xyz'],
                                  coords={'time': time, 'xyz': np.arange(3)})
    #da.attrs = {'nlines': len(time)} #number of orbit vectors in annotation file
    da.attrs = {'orbit_pass':orbit_pass,'platform_heading':platform_heading}
    return da


def strtime2numtime( strtime, fmt='%Y-%m-%dT%H:%M:%S.%f'):
    """
    Convert string time to numeric time.
    """
    dtime = datetime.strptime(strtime, fmt)
    #numtime = date2num(dtime, self.read_field('time').units)
    TIMEUNITS = 'seconds since 1990-01-01T00:00:00'
    # 'seconds since 2014-01-01 00:00:00'
    numtime = netCDF4.date2num(dtime,TIMEUNITS )
    return numtime

def doppler_centroid_estimates(nb_dcestimate,nb_geoDcPoly,nb_dataDcPoly,
                nb_fineDce,dc_azimuth_time,dc_t0,dc_geoDcPoly,
                dc_dataDcPoly,dc_rmserr,dc_rmserrAboveThres,dc_azstarttime,
                dc_azstoptime,dc_slantRangeTime,dc_frequency):
    """

    :param nb_dcestimate:
    :param nb_geoDcPoly:
    :param nb_dataDcPoly:
    :param nb_fineDce:
    :param dc_azimuth_time:
    :param dc_t0:
    :param dc_geoDcPoly:
    :param dc_dataDcPoly:
    :param dc_rmserr:
    :param dc_rmserrAboveThres:
    :param dc_azstarttime:
    :param dc_azstoptime:
    :param dc_slantRangeTime:
    :param dc_frequency:
    :return:
    """
    ds = xr.Dataset()
    ds['t0'] = xr.DataArray(dc_t0.astype(float),dims=['n_estimates'])
    ds['geo_polynom'] = xr.DataArray(dc_geoDcPoly,dims=['n_estimates','ngeocoeffs'])
    ds['data_polynom'] = xr.DataArray(dc_dataDcPoly,dims=['n_estimates','ndatacoeffs'])
    dims = (nb_dcestimate, nb_fineDce)
    ds['azimuth_time'] = xr.DataArray(np.empty(dims, dtype='float64'),dims=['n_estimates','nb_fine_dce'])
    ds['azimuth_time_start'] =  xr.DataArray(np.empty((nb_dcestimate), dtype='float64'),dims=['n_estimates'])
    ds['azimuth_time_stop'] = xr.DataArray(np.empty((nb_dcestimate), dtype='float64'), dims=['n_estimates'])
    ds['data_rms'] = xr.DataArray(dc_rmserr.astype(float),dims=['n_estimates'])
    ds['slant_range_time'] = xr.DataArray(dc_slantRangeTime.reshape(dims),dims=['n_estimates','nb_fine_dce'])
    ds['frequency'] = xr.DataArray(dc_frequency.reshape(dims), dims=['n_estimates', 'nb_fine_dce'])
    ds['data_rms_threshold'] = xr.DataArray(dc_rmserrAboveThres,dims=['n_estimates'])
    for iline in range(nb_dcestimate):
        strtime = dc_azimuth_time[iline]
        ds['azimuth_time'].values[iline, :] = strtime2numtime(strtime)
        strtime = dc_azstarttime[iline]
        ds['azimuth_time_start'].values[iline] = strtime2numtime(strtime)
        strtime = dc_azstoptime[iline]
        ds['azimuth_time_stop'].values[iline] = strtime2numtime(strtime)
    ds.attrs['description'] = 'annotations for Doppler centroid estimates'
    #ds.attrs['n_estimates'] = len(ds['t0'])
    #ds.attrs['n_fineDCE'] = nb_fineDce
    #ds.attrs['ngeocoeffs'] = nb_geoDcPoly
    #ds.attrs['ndatacoeffs'] = nb_dataDcPoly
    return ds

def subswath_image(number_of_lines,range_sampling_rate,azimuth_steering_rate,slant_range_time_image,
                   azimuth_time_interval,radar_frequency,number_of_samples,incidence_angle_mid_swath):
    res = {'number_of_lines':number_of_lines,
           'range_sampling_rate':range_sampling_rate,
           'azimuth_steering_rate':azimuth_steering_rate,
           'slant_range_time_image':slant_range_time_image,
           'azimuth_time_interval':azimuth_time_interval,
           'radar_frequency':radar_frequency,
           'number_of_samples':number_of_samples,
           'incidence_angle_mid_swath':incidence_angle_mid_swath
           }
    return res


def azimuth_fmrate(azimuthtime, t0, c0, c1, c2, polynomial):
    """

    :param azimuthtime:
    :param t0:
    :param c0:
    :param c1:
    :param c2:
    :param polynomial:
    :return:
    """
    azimuthtime = np.array([strtime2numtime(x) for x in azimuthtime])
    #azimuthtime = azimuthtime.astype(float)
    if ( np.sum([c.size for c in [c0,c1,c2]]) != 0) and (polynomial.size == 0):
        # old annotation
        polynomial = np.stack([c0, c1, c1], axis=1)


    return pd.DataFrame(
        {
            't0': t0,
            'polynomial': [ Polynomial(p) for p in polynomial ],
            'azimuth_time':azimuthtime
        }, index=azimuthtime
    )

# dict of compounds variables.
# compounds variables are variables composed of several variables.
# the key is the variable name, and the value is a python structure,
# where leaves are jmespath in xpath_mappings
compounds_vars = {
    'safe_attributes': {
        'ipf_version': 'manifest.ipf_version',
        'swath_type': 'manifest.swath_type',
        'polarizations': 'manifest.polarizations',
        'product_type': 'manifest.product_type',
        'mission': 'manifest.mission',
        'satellite': 'manifest.satellite',
        'start_date': 'manifest.start_date',
        'stop_date': 'manifest.stop_date',
        'footprints': 'manifest.footprints'
    },
    'files': {
        'func': df_files,
        'args': (
            'manifest.annotation_files', 'manifest.measurement_files', 'manifest.noise_files',
            'manifest.calibration_files')
    },
    'sigma0_lut': {
        'func': signal_lut,
        'args': ('calibration.atrack', 'calibration.xtrack', 'calibration.sigma0_lut')
    },
    'gamma0_lut': {
        'func': signal_lut,
        'args': ('calibration.atrack', 'calibration.xtrack', 'calibration.gamma0_lut')
    },
    'noise_lut_range': {
        'func': noise_lut_range,
        'args': ('noise.range.atrack', 'noise.range.xtrack', 'noise.range.noiseLut')
    },
    'noise_lut_azi': {
        'func': noise_lut_azi,
        'args': (
            'noise.azi.atrack', 'noise.azi.atrack_start', 'noise.azi.atrack_stop',
            'noise.azi.xtrack_start',
            'noise.azi.xtrack_stop', 'noise.azi.noiseLut',
            'noise.azi.swath')
    },
    'denoised': ('annotation.pol', 'annotation.denoised'),

    'incidence': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.incidence')
    },
    'elevation': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.elevation')
    },
    'longitude': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.longitude')
    },
    'latitude': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.latitude')
    },
    'height': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.height')
    },
    'azimuth_time': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.azimuth_time')
    },
    'slant_range_time': {
        'func': geolocation_grid,
        'args': ('annotation.atrack', 'annotation.xtrack', 'annotation.slant_range_time')
    },
    'bursts': {
        'func': bursts,
        'args': ('annotation.lines_per_burst', 'annotation. samples_per_burst', 'annotation. burst_azimuthTime',
                 'annotation. burst_azimuthAnxTime', 'annotation. burst_sensingTime', 'annotation.burst_byteOffset',
                 'annotation. burst_firstValidSample', 'annotation.burst_lastValidSample')
    },
    'orbit': {
        'func': orbit,
        'args': ('annotation.orbit_time', 'annotation.orbit_frame',
                 'annotation.orbit_pos_x', 'annotation.orbit_pos_y', 'annotation.orbit_pos_z',
                 'annotation.orbit_vel_x', 'annotation.orbit_vel_y', 'annotation.orbit_vel_z',
                 'annotation.pass','annotation.platform_heading')
    },
    'azimuth_fmrate': {
        'func': azimuth_fmrate,
        'args': (
            'annotation.fmrate_azimuthtime', 'annotation.fmrate_t0',
            'annotation.fmrate_c0', 'annotation.fmrate_c1', 'annotation.fmrate_c2',
            'annotation.fmrate_azimuthFmRatePolynomial')
    },
    'doppler_estimate': {
        'func':doppler_centroid_estimates,
        'args':('annotation.nb_dcestimate','annotation.nb_geoDcPoly','annotation.nb_dataDcPoly',
                'annotation.nb_fineDce','annotation.dc_azimuth_time','annotation.dc_t0','annotation.dc_geoDcPoly',
                'annotation.dc_dataDcPoly','annotation.dc_rmserr','annotation.dc_rmserrAboveThres','annotation.dc_azstarttime',
                'annotation.dc_azstoptime','annotation.dc_slantRangeTime','annotation.dc_frequency'

        ),
    },
    'subswath_image': {
        'func': subswath_image,
        'args':('annotation.number_of_lines','annotation.range_sampling_rate','annotation.azimuth_steering_rate',
                'annotation.slant_range_time_image','annotation.azimuth_time_interval','annotation.radar_frequency',
                'annotation.number_of_samples','annotation.incidence_angle_mid_swath')
    }

}



