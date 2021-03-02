"""
dem.py provides a class for working with digital elevation models (DEMs)
"""
import pyproj
import warnings
from geoutils.satimg import SatelliteImage
from pyproj import Transformer

def parse_vref_from_product(product):

    # sources for defining vertical references:
    # AW3D30: https://www.eorc.jaxa.jp/ALOS/en/aw3d30/aw3d30v11_format_e.pdf
    # SRTMGL1: https://lpdaac.usgs.gov/documents/179/SRTM_User_Guide_V3.pdf
    # SRTMv4.1: http://www.cgiar-csi.org/data/srtm-90m-digital-elevation-database-v4-1
    # ASTGTM2/ASTGTM3: https://lpdaac.usgs.gov/documents/434/ASTGTM_User_Guide_V3.pdf
    # NASADEM: https://lpdaac.usgs.gov/documents/592/NASADEM_User_Guide_V1.pdf !! HGTS is ellipsoid, HGT is EGM96 geoid !!
    # ArcticDEM (mosaic and strips): https://www.pgc.umn.edu/data/arcticdem/
    # REMA (mosaic and strips): https://www.pgc.umn.edu/data/rema/
    # TanDEM-X 90m global: https://geoservice.dlr.de/web/dataguide/tdm90/
    # COPERNICUS DEM: https://spacedata.copernicus.eu/web/cscda/dataset-details?articleId=394198

    if product in ['ArcticDEM/REMA','TDM1','NASADEM-HGTS']:
        vref = 'WGS84'
    elif product in ['AW3D30','SRTMv4.1','SRTMGL1','ASTGTM2','NASADEM-HGT']:
        vref = 'EGM96'
    elif product in ['COPDEM']:
        vref = 'EGM08'
    else:
        vref = None

    return vref

class DEM(SatelliteImage):

    def __init__(self, filename, vref=None, vref_grid=None, ccrs = None, read_vref_from_prod=True, silent=False, **kwargs):

        super().__init__(filename, **kwargs)

        if self.nbands > 1:
            raise ValueError('DEM rasters should be composed of only one band only')

        # priority to user input
        self.vref = vref
        self.vref_grid = vref_grid
        self.ccrs = ccrs

        # trying to get vref from product name
        if read_vref_from_prod:
            self.__parse_vref_from_fn(silent=silent)


    def __parse_vref_from_fn(self,silent=False):

        """
        Attempts to pull vertical reference from product name identified by SatImg
        """

        if self.product is not None:
            vref = parse_vref_from_product(self.product)
            if vref is not None and self.vref is None:
                if not silent:
                    print('From product name "'+ str(self.product)+'": setting vertical reference as ' + str(self.vref))
                self.vref = vref
            elif vref is not None and self.vref is not None:
                if not silent:
                    print('Leaving user input of ' + str(self.vref) + ' for vertical reference despite reading ' + str(
                        vref) + ' from product name')
            else:
                if not silent:
                    print('Could not find a vertical reference based on product name: "'+str(self.product)+'"')


    def set_vref(self,vref_name=None,vref_grid=None,compute_ccrs=False):
        """
        Set vertical reference with a name or with a grid

        :param vref_name: Name of geoid
        :param vref_grid: PROJ DATA geoid grid file name
        :param compute_ccrs: Whether to compute the ccrs (possibly reading pyproj-data grid file)
        :type vref_name: str
        :type vref_grid: str
        :type compute_ccrs: boolean

        :return:
        """

        #for names, we only look for WGS84 ellipsoid or the EGM96/EGM08 geoids: those are used 99% of the time
        if isinstance(vref_name, str):
            if isinstance(vref_grid, str):
                print('Both a vertical reference name and vertical grid are provided: defaulting to using name only.')
            if vref_name == 'WGS84':
                self.vref_grid = None
                self.vref = 'WGS84'  # WGS84 ellipsoid
            if vref_name == 'EGM08':
                self.vref_grid = 'us_nga_egm08_25.tif'  # EGM2008 at 2.5 minute resolution
                self.vref = 'EGM08'
            elif vref_name == 'EGM96':
                self.vref_grid = 'us_nga_egm96_15.tif'  # EGM1996 at 15 minute resolution
                self.vref = 'EGM96'
            else:
                raise ValueError(
                    'Vertical reference name must be either "WGS84", "EGM96" or "EGM08". Otherwise, provide only'
                    'a geoid grid from PROJ DATA: https://github.com/OSGeo/PROJ-data')
        elif not isinstance(vref_grid, str):
            raise ValueError('Vertical reference grid name must be PROJ DATA file name, '
                             'such as: "us_noaa_geoid06_ak.tif" for the Alaska GEOID2006')
        else:
            self.vref = 'Unknown vertical reference name'
            self.vref_grid = vref_grid

        # no deriving the ccrs until those are used in a reprojection (requires pyproj-data grids = ~500Mo)
        if compute_ccrs:
            if self.vref == 'WGS84':
                # the WGS84 ellipsoid essentially corresponds to no vertical reference in pyproj
                self.ccrs = pyproj.CRS(self.crs)
            else:
                # for other vrefs, keep same horizontal projection and add geoid grid (the "dirty" way: because init is so
                # practical and still going to be used for a while)
                # see https://gis.stackexchange.com/questions/352277/including-geoidgrids-when-initializing-projection-via-epsg/352300#352300
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", module="pyproj")
                    self.ccrs = pyproj.Proj(init="EPSG:" + str(int(self.crs.to_epsg())), geoidgrids=self.vref_grid).crs

    def to_vref(self,vref_name='EGM96',vref_grid=None):

        """
        Convert between vertical references: ellipsoidal heights or geoid grids

        :param vref_name: Name of geoid
        :param vref_grid: PROJ DATA geoid grid file name
        :type vref_name: str
        :type vref_grid: str

        :return:
        """

        # all transformations grids file are described here: https://github.com/OSGeo/PROJ-data
        if self.vref is None and self.vref_grid is None:
            raise ValueError('The current DEM has not vertical reference: need to set one before attempting a conversion '
                             'towards another vertical reference.')
        elif isinstance(self.vref,str) and self.vref_grid is None:
            # to set the vref grid names automatically EGM96/08 for geoids + compute the ccrs
            self.set_vref(vref_name=self.vref,compute_ccrs=True)

        # inital ccrs
        ccrs_init = self.ccrs.copy()

        # destination crs

        # set the new reference (before calculation doesn't change anything, we need to update the data manually anyway)
        self.set_vref(vref_name=vref_name,vref_grid=vref_grid,compute_ccrs=True)
        ccrs_dest = self.ccrs.copy()

        # transform matrix
        transformer = Transformer.from_crs(ccrs_init, ccrs_dest)
        meta = self.ds.meta
        zz = self.data[0,:]
        xx, yy = self.coords(offset='center')
        zz_trans = transformer.transform(xx,yy,zz)
        zz[0,:] = zz_trans

        # update raster
        self._update(metadata=meta,imgdata=zz)