# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/060_callback.core.ipynb (unless otherwise specified).

__all__ = ['GamblersCallback', 'TransformScheduler', 'ShowGraph', 'ShowGraphCallback2', 'UBDAug',
           'WeightedPerSampleLoss']

# Cell
from ..imports import *
from ..utils import *
from ..data.preprocessing import *
from ..data.transforms import *
from ..models.layers import *
from fastai.callback.all import *

# Cell
import torch.multiprocessing
torch.multiprocessing.set_sharing_strategy('file_system')

# Cell
class GamblersCallback(Callback):
    "A callback to use metrics with gambler's loss"
    def after_loss(self): self.learn.pred = self.learn.pred[..., :-1]

# Cell
class TransformScheduler(Callback):
    "A callback to schedule batch transforms during training based on a function (sched_lin, sched_exp, sched_cos (default), etc)"
    def __init__(self, schedule_func:callable, show_plot:bool=False):
        self.schedule_func,self.show_plot = schedule_func,show_plot
        self.mult = []

    def before_fit(self):
        for pct in np.linspace(0, 1, len(self.dls.train) * self.n_epoch): self.mult.append(self.schedule_func(pct))
        # get initial magnitude values and update initial value
        self.mag = []
        self.mag_tfms = []
        for t in self.dls.after_batch:
            if hasattr(t, 'magnitude'):
                self.mag.append(t.magnitude)
                t.magnitude *= self.mult[0]
                self.mag_tfms.append(t)

    def after_batch(self):
        if self.training and len(self.mag_tfms)>0 and self.train_iter < len(self.mult):
            # set values for next batch
            for t,m in zip(self.mag_tfms, self.mag):
                t.magnitude = m * self.mult[self.train_iter]

    def after_fit(self):
        if self.show_plot and self.mult != [] and len(self.mag_tfms)>0:
            print()
            plt.plot(self.mult)
            plt.title('Scheduled tfms')
            plt.show()
            print()
            self.show_plot = False
        # set values to initial values
        for t,m in zip(self.mag_tfms, self.mag): t.magnitude = m

    def __repr__(self):
        return f'{self.__class__.__name__}({self.schedule_func})'

# Cell
class ShowGraph(Callback):
    "(Modified) Update a graph of training and validation loss"
    order,run_valid=65,False
    names = ['train', 'valid']
    def __init__(self, plot_metrics:bool=True, final_losses:bool=False):
        store_attr("plot_metrics,final_losses")


    def before_fit(self):
        self.run = not hasattr(self.learn, 'lr_finder') and not hasattr(self, "gather_preds")
        if not(self.run): return
        self.nb_batches = []

    def after_train(self): self.nb_batches.append(self.train_iter)

    def after_epoch(self):
        "Plot validation loss in the pbar graph"
        if not self.nb_batches: return
        rec = self.learn.recorder
        iters = range_of(rec.losses)
        val_losses = [v[1] for v in rec.values]
        x_bounds = (0, (self.n_epoch - len(self.nb_batches)) * self.nb_batches[0] + len(rec.losses))
        y_min = min((min(rec.losses), min(val_losses)))
        y_max = max((max(rec.losses), max(val_losses)))
        margin = (y_max - y_min) * .05
        y_bounds = (y_min - margin, y_max + margin)
        self.update_graph([(iters, rec.losses), (self.nb_batches, val_losses)], x_bounds, y_bounds)

    def after_fit(self):
        plt.close(self.graph_ax.figure)
        if self.plot_metrics: self.learn.plot_metrics(final_losses=self.final_losses)

    def update_graph(self, graphs, x_bounds=None, y_bounds=None, figsize=(6,4)):
        if not hasattr(self, 'graph_fig'):
            self.graph_fig, self.graph_ax = plt.subplots(1, figsize=figsize)
            self.graph_out = display(self.graph_ax.figure, display_id=True)
        self.graph_ax.clear()
        if len(self.names) < len(graphs): self.names += [''] * (len(graphs) - len(self.names))
        for g,n in zip(graphs,self.names): self.graph_ax.plot(*g, label=n)
        self.graph_ax.legend(loc='upper right')
        self.graph_ax.grid(color='gainsboro', linewidth=.5)
        if x_bounds is not None: self.graph_ax.set_xlim(*x_bounds)
        if y_bounds is not None: self.graph_ax.set_ylim(*y_bounds)
        self.graph_ax.set_title(f'Losses\nepoch: {self.epoch +1}/{self.n_epoch}')
        self.graph_out.update(self.graph_ax.figure)

ShowGraphCallback2 = ShowGraph

# Cell
class UBDAug(Callback):
    r"""A callback to implement the uncertainty-based data augmentation."""

    def __init__(self, batch_tfms:list, N:int=2, C:int=4, S:int=1):
        r'''
        Args:
            batch_tfms:   list of available transforms applied to the combined batch. They will be applied in addition to the dl tfms.
            N:            # composition steps (# transforms randomly applied to each sample)
            C:            # augmented data per input data (# times N transforms are applied)
            S:            # selected data points used for training (# augmented samples in the final batch from each original sample)
        '''

        self.C, self.S = C, min(S, C)
        self.batch_tfms = L(batch_tfms)
        self.n_tfms = len(self.batch_tfms)
        self.N = min(N, self.n_tfms)

    def before_fit(self):
        assert hasattr(self.loss_func, 'reduction'), "You need to pass a loss_function with a 'reduction' attribute"
        self.red = self.loss_func.reduction

    def before_batch(self):
        if self.training:
            with torch.no_grad():
                setattr(self.loss_func, 'reduction', 'none')
                for i in range(self.C):
                    idxs = np.random.choice(self.n_tfms, self.N, False)
                    x_tfm = compose_tfms(self.x, self.batch_tfms[idxs], split_idx=0)
                    loss = self.loss_func(self.learn.model(x_tfm), self.y).reshape(-1,1)
                    if i == 0:
                        x2 = x_tfm.unsqueeze(1)
                        max_loss = loss
                    else:
                        losses = torch.cat((max_loss, loss), dim=1)
                        x2 = torch.cat((x2, x_tfm.unsqueeze(1)), dim=1)
                        x2 = x2[np.arange(x2.shape[0]).reshape(-1,1), losses.argsort(1)[:, -self.S:]]
                        max_loss = losses.max(1)[0].reshape(-1,1)
                setattr(self.loss_func, 'reduction', self.red)
            x2 = x2.reshape(-1, self.x.shape[-2], self.x.shape[-1])
            if self.S > 1: self.learn.yb = (torch_tile(self.y, 2),)
            self.learn.xb = (x2,)

    def __repr__(self): return f'UBDAug({[get_tfm_name(t) for t in self.batch_tfms]})'

# Cell

class WeightedPerSampleLoss(Callback):
    order = 65

    def __init__(self, instance_weights):
        store_attr()

    def before_fit(self):
        self.old_loss = self.learn.loss_func
        self.reduction = getattr(self.learn.loss_func, 'reduction', None)
        self.learn.loss_func = _PerInstanceLoss(crit=self.learn.loss_func)
        assert len(self.instance_weights) == len(self.learn.dls.train.dataset) + len(self.learn.dls.valid.dataset)
        self.instance_weights = tensor(self.instance_weights).to(self.learn.dls.device)

    def before_batch(self):
        if self.training:
            original_idxs = tensor([self.learn.dls.train.split_idxs[self.learn.dls.train.idxs]], device=self.x.device)[0]
            self.learn.loss_func.weights = self.instance_weights[original_idxs]
        else:
            original_idxs = tensor([self.learn.dls.valid.split_idxs[self.learn.dls.valid.idxs]], device=self.x.device)[0]
            self.learn.loss_func.weights = self.instance_weights[original_idxs]

    def after_fit(self):
        self.learn.loss_func = self.old_loss
        if self.reduction is not None:
            self.learn.loss_func.reduction = self.reduction


class _PerInstanceLoss(Module):
    def __init__(self, crit):
        self.crit = crit
        self.crit.reduction = 'none'
        self.weights = None

    def forward(self, input, target):
        return (self.crit(input, target) * self.weights / self.weights.sum()).sum()