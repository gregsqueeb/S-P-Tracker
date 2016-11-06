
import math

# glBegin parameters
class GL:Lines,LineStrip,Triangles,Quads=range(4)
# getCarSate parameters
class CS:SpeedMS,SpeedMPH,SpeedKMH,Gas,Brake,Clutch,Gear,Aero,BestLap,CamberRad,AccG,CGHeight,DriftBestLap,DriftLastLap,DriftPoints,DriveTrainSpeed,DY,RPM,Load,InstantDrift,IsDriftInvalid,IsEngineLimiterOn,LapCount,LapInvalidated,LapTime,LastFF,LastLap,LocalAngularVelocity,LocalVelocity,Mz,NdSlip,NormalizedSplinePosition,PerformanceMeter,SlipAngle,SlipAngleContactPatch,SlipRatio,SpeedTotal,Steer,SuspensionTravel,TurboBoost,TyreDirtyLevel,TyreContactNormal,TyreContactPoint,TyreHeadingVector,TyreLoadedRadius,TyreRadius,TyreRightVector,TyreSlip,TyreSurfaceDef,TyreVelocity,Velocity,WheelAngularSpeed,WorldPosition,Caster,CurrentTyresCoreTemp,LastTyresTemp,DynamicPressure,RideHeight,ToeInDeg,CamberDeg = range(60)
# Using ac.getCarState with the following paramters : 
# TyreContactPoint, TyreContactNormal, TyreHeadingVector, TyreRightVector
# It is necessary to specify the tyre identifier as third parameter:
class WHEELS:FL,FR,RL,RR=range(4)
# The call will have the following syntax:
# ac.getCarState(<CAR_ID>,TyreContactPoint,<WHEEL_IDENTIFIER>)
# if no wheel identifier is specified WHEELS.FL is assumed

# Using ac.getCarState with Aero parameter it is necessary to specify
class AERO:CD,CL_Front,CL_Rear=range(3)
# as third parameter, if no AERO parameter is provided, CD is assumed
############# MATH ############

class Vec2f:
    def __init__(self,x=0,y=0):
        self.x=float(x)
        self.y=float(y)

    def __add__(self,other):
        return Vec2f(self.x+other.x , self.y + other.y)

    def __sub__(self,other):
        return Vec2f(self.x-other.x , self.y - other.y)

    def normalize(self):
        l=math.sqrt(self.x*self.x + self.y*self.y)
        self.x/=l
        self.y/=l

    def __mul__(self,val):
        return Vec2f(self.x * val , self.y*val)




