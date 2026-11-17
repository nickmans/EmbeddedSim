"""Regenerate standalone scientific plots from the exported robot CSV."""
import numpy as np
from common import OUT
def load(name):return np.genfromtxt(OUT/(name+'.csv'),delimiter=',',names=True)

def render():
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    d=load('main');t=d['time_s']
    fig,ax=plt.subplots(figsize=(8,7));ax.plot(d['x_m'],d['y_m'],label='torque-driven model')
    ax.plot(d['odom_x_m'],d['odom_y_m'],'--',label='firmware encoder odometry')
    for start,label in [(.2,'straight'),(2.8,'turn'),(5.2,'curve'),(7.8,'reverse')]:
        i=np.argmin(abs(t-start)); offsets={.2:(8,12),2.8:(-60,18),5.2:(-60,-35),7.8:(10,-15)}
        ax.plot(d['x_m'][i],d['y_m'][i],'o',markersize=3)
        ax.annotate(label,(d['x_m'][i],d['y_m'][i]),xytext=offsets[start],textcoords='offset points',arrowprops={'arrowstyle':'-','color':'gray'})
    ax.set(xlabel='World x (m)',ylabel='World y (m)',title='Planar differential drive — illustrative, not hardware validation');ax.axis('equal');ax.grid(alpha=.3);ax.legend();fig.tight_layout();fig.savefig(OUT/'trajectory.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(6,1,figsize=(11,13),sharex=True)
    for side in 'lr':
        ax[0].plot(t,d['w'+side+'_rad_s'],label=side+' model');ax[0].plot(t,d['reference_'+side+'_rad_s'],'--',label=side+' target')
        ax[1].plot(t,d['i'+side+'_A'],label=side)
        ax[2].plot(t,d['duty_'+side]*d['dir_'+side],label=side+' measured duty*DIR')
    ax[3].plot(t,d['heading_rad'],label='model');ax[3].plot(t,np.unwrap(d['odom_heading_rad']),'--',label='firmware')
    ax[4].plot(t,np.hypot(d['x_m']-d['odom_x_m'],d['y_m']-d['odom_y_m']))
    ax[5].plot(t,d['resistance_r_Nm'])
    for a,label in zip(ax,['Wheel speed (rad/s)','Motor current (A)','Signed duty','Heading (rad)','Position error (m)','Right resistance (N m)']):a.set_ylabel(label);a.grid(alpha=.3)
    for a in ax[:4]:a.legend(loc='best')
    ax[-1].set_xlabel('Renode virtual time (s)');fig.tight_layout();fig.savefig(OUT/'timeseries.png',dpi=150);plt.close(fig)

if __name__=='__main__':render()
