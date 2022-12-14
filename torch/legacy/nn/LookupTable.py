import torch
from .Module import Module
from .utils import clear

class LookupTable(Module):

    def __init__(self, nIndex, nOutput, paddingValue=-1, maxNorm=None, normType=None):
        super(LookupTable, self).__init__()
        self.weight = torch.Tensor(nIndex, nOutput)
        self.gradWeight = torch.Tensor(nIndex, nOutput).zero_()
        self.paddingValue = paddingValue
        self.maxNorm = maxNorm
        self.normType = normType
        self.shouldScaleGradByFreq = False

        self._gradOutput = None
        self._sorted = None
        self._indices = None

        self._count = torch.IntTensor()
        self._input = torch.LongTensor()

        self.reset()

    def accUpdateOnly(self):
        self.gradWeight = None
        return self

    def setPadding(self, paddingValue):
        self.paddingValue = paddingValue
        return self

    def setMaxNorm(self, maxNorm):
        self.maxNorm = maxNorm
        return self

    def setNormType(self, normType):
        self.normType = normType
        return self

    def scaleGradByFreq(self):
        self.shouldScaleGradByFreq = True
        return self

    def reset(self, stdv=1):
        self.weight.normal_(0, stdv)

    def _makeInputContiguous(self, input):
        # make sure input is a contiguous torch.LongTensor
        if not input.isContiguous() or type(input) != type(self._input):
            self.copiedInput = True
            self._input.resize_(input.size()).copy_(input)
            return self._input
        else:
            self.copiedInput = False
            return input

    def updateOutput(self, input):
        self.renorm(input)
        input = self._makeInputContiguous(input)
        if input.dim() == 1:
           torch.indexSelect(self.output, self.weight, 0, input)
        elif input.dim() == 2:
           torch.indexSelect(self.output, self.weight, 0, input.view(-1))
           self.output = self.output.view(input.size(0), input.size(1), self.weight.size(1))
        else:
           raise RuntimeError("input must be a vector or matrix")

        return self.output


    def updateGradInput(self, input, gradOutput):
        # the input can be of any type (as in the forward it's
        # converted anyway to LongTensor) thus, need to allocate
        # new memory each time the user changes the input type
        if type(self.gradInput) != type(input):
            self.gradInput = input.new()

        if not self.gradInput.isSameSizeAs(input):
            self.gradInput.resizeAs_(input).zero_()

        return self.gradInput


    def accGradParameters(self, input, gradOutput, scale=1):
        input = self._input if self.copiedInput else input
        if input.dim() == 2:
            input = input.view(-1)
        elif input.dim() != 1:
            raise RuntimeError("input must be a vector or matrix")

        if not gradOutput.isContiguous():
            self._gradOutput = self._gradOutput or gradOutput.new()
            self._gradOutput.resizeAs_(gradOutput).copy_(gradOutput)
            gradOutput = self._gradOutput

        self._backend.LookupTable_accGradParameters(
            self._backend.library_state,
            input,
            gradOutput,
            self.gradWeight,
            self._count,
            self._sorted,
            self._indices,
            self.shouldScaleGradByFreq,
            self.paddingValue or 0,
            scale
        )

    def renorm(self, input):
        if not self.maxNorm:
           return

        # copy input into _input, so _input is continous.
        # The copied _input will be modified in the C code.
        self._input.resize_(input.size()).copy_(input)
        row_idx = self._input
        if row_idx.dim() == 2:
           row_idx = row_idx.view(-1)
        elif row_idx.dim() != 1:
           raise RuntimeError("input must be a vector or matrix")

        # "row_idx" and "weight" will be modified in the C code
        self._backend.LookupTable_renorm(
            self._backend.library_state,
            row_idx,
            self.weight,
            self.maxNorm,
            self.normType or 2
        )

    def type(self, type=None, tensorCache=None):
        if not type:
            return self._type
        super(LookupTable, self).type(type, tensorCache)

        if type == 'torch.cuda.FloatTensor':
            # CUDA uses _sorted and _indices temporary tensors
            self._sorted = torch.cuda.LongTensor()
            self._indices = torch.cuda.LongTensor()
            self._count = torch.cuda.LongTensor()
            self._input = torch.cuda.LongTensor()
        else:
            # self._count and self._input should only be converted if using Cuda
            self._count = torch.IntTensor()
            self._input = torch.LongTensor()

        return self

    def clearState(self):
        clear(self, '_count', '_input', '_sorted', '_indices', '_gradOutput')
        return super(LookupTable, self).clearState()

