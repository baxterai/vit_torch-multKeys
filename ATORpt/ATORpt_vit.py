"""ATORpt_vit.py

# Author:
Brian Pulfer - Copyright (c) 2022 Peutlefaire (https://github.com/BrianPulfer)
Richard Bruce Baxter - Copyright (c) 2022 Baxter AI (baxterai.com)

# License:
MIT License

# Installation:
see ATORpt_main.py

# Description:
ATORpt vit

"""

import torch as pt
import torch.nn as nn

from ATORpt_globalDefs import *
import ATORpt_operations

#orig: https://github.com/BrianPulfer/PapersReimplementations/blob/master/vit/vit_torch.py

class ViTClass(nn.Module):
	def __init__(self, inputShape, numberOfPatches, numberOfHiddenDimensions, numberOfHeads, numberOfOutputDimensions):
		super(ViTClass, self).__init__()

		self.inputShape = inputShape
		numberOfChannels, imageWidth, imageHeight = inputShape
		self.numberOfPatches = numberOfPatches
		self.numberOfHeads = numberOfHeads
		self.patchSize = ATORpt_operations.getPatchSize(inputShape, numberOfPatches)
		self.numberOfHiddenDimensions = numberOfHiddenDimensions
		self.numberOfInputDimensions = ATORpt_operations.getInputDim(inputShape, self.patchSize)

		if(inputShape[1] % numberOfPatches != 0):
			print("inputShape[1] % numberOfPatches != 0")
		if(inputShape[2] % numberOfPatches != 0):
			print("inputShape[2] % numberOfPatches != 0")

		if(useParallelisedGeometricHashing):
			self.numberOfHiddenDimensionsPreMSA = self.numberOfInputDimensions
		else:
			self.numberOfHiddenDimensionsPreMSA = self.numberOfHiddenDimensions

		self.linearMapper = nn.Linear(self.numberOfInputDimensions, self.numberOfHiddenDimensionsPreMSA)
		
		self.classificationToken = nn.Parameter(pt.rand(1, self.numberOfHiddenDimensionsPreMSA))
		
		self.layerNormalisation1 = nn.LayerNorm((ATORpt_operations.getHiddenLayerNumTokens(numberOfPatches), self.numberOfHiddenDimensionsPreMSA))
		
		self.msa = MSAClass(self.numberOfHiddenDimensions, numberOfHeads)

		self.layerNormalisation2 = nn.LayerNorm((self.numberOfPatches ** 2 + 1, self.numberOfHiddenDimensions))

		self.encoderMLP = nn.Sequential(
			nn.Linear(self.numberOfHiddenDimensions, self.numberOfHiddenDimensions),
			nn.ReLU()
		)

		self.outputMLP = nn.Sequential(
			nn.Linear(self.numberOfHiddenDimensions, numberOfOutputDimensions),
			nn.Softmax(dim=-1)
		)

	def forward(self, images, posEmbeddingsAbsoluteGeoNormalised=None):

		batchSize, numberOfChannels, imageHeight, imageWidth = images.shape
		tokens = ATORpt_operations.createLinearPatches(images, self.numberOfPatches)

		tokens = self.linearMapper(tokens)

		tokens = pt.stack([pt.vstack((self.classificationToken, tokens[i])) for i in range(len(tokens))])

		tokens = self.layerNormalisation1(tokens)

		if(useParallelisedGeometricHashing):
			#add positional embedding for classification token (0, 0)
			posEmbeddingClassificationToken = pt.unsqueeze(pt.unsqueeze(pt.zeros(numberOfGeometricDimensions), 0), 0).repeat(batchSize, 1, 1)
			posEmbeddingsAbsoluteGeoNormalised = pt.cat([posEmbeddingClassificationToken, posEmbeddingsAbsoluteGeoNormalised], dim=1)
			
			tokensAndPosEmbeddings = pt.cat([tokens, posEmbeddingsAbsoluteGeoNormalised], dim=2)
			tokens = tokensAndPosEmbeddings
		else:
			posEmbeddings = ATORpt_operations.getPositionalEmbeddings(ATORpt_operations.getHiddenLayerNumTokens(self.numberOfPatches), self.numberOfHiddenDimensions).repeat(batchSize, 1, 1)
			tokens = tokens + posEmbeddings   #add the embeddings to the tokens

		print("tokens.shape = ", tokens.shape)
		out = tokens + self.msa(tokens)

		out = out + self.encoderMLP(self.layerNormalisation2(out))

		out = out[:, 0]

		pred = self.outputMLP(out)
	
		return pred

class MSAClass(nn.Module):
	def __init__(self, numberOfHiddenDimensions, numberOfHeads=2):
		super(MSAClass, self).__init__()
		self.numberOfHiddenDimensions = numberOfHiddenDimensions
		self.numberOfHeads = numberOfHeads

		if(numberOfHiddenDimensions % numberOfHeads != 0):
			print("(numberOfHiddenDimensions % numberOfHeads != 0")
			exit()

		numberOfHeadDimensions = int(numberOfHiddenDimensions / numberOfHeads)
		self.qWeights = nn.ModuleList([nn.Linear(numberOfHeadDimensions, numberOfHeadDimensions) for _ in range(self.numberOfHeads)])
		self.kWeights = nn.ModuleList([nn.Linear(numberOfHeadDimensions, numberOfHeadDimensions) for _ in range(self.numberOfHeads)])
		self.vWeights = nn.ModuleList([nn.Linear(numberOfHeadDimensions, numberOfHeadDimensions) for _ in range(self.numberOfHeads)])
		self.numberOfHeadDimensions = numberOfHeadDimensions
		self.softmax = nn.Softmax(dim=-1)

	def forward(self, sequences):
		result = []
		#sequences shape = batchSize, sequenceLength, numberOfHiddenDimensions
		for sequence in sequences:
			#sequence shape = sequenceLength, numberOfHiddenDimensions
			seqResult = []
			for head in range(self.numberOfHeads):
			
				seq = sequence[:, head * self.numberOfHeadDimensions: (head + 1) * self.numberOfHeadDimensions]	
				#seq shape = batchSize, sequenceLength, numberOfHeads, numberOfHiddenDimensions / numberOfHeads
				
				qWeightsHead = self.qWeights[head]
				kWeightsHead = self.kWeights[head]
				vWeightsHead = self.vWeights[head]
				q = qWeightsHead(seq)
				k = kWeightsHead(seq)
				v = vWeightsHead(seq)

				if(useMultKeys):
					kdots = k @ k.T
					dots = q @ kdots.T
				else:		  
					dots = q @ k.T

				attention = self.softmax(dots / (self.numberOfHeadDimensions ** 0.5))
				resultN = attention @ v

				seqResult.append(resultN)
			result.append(pt.hstack(seqResult))
		out = pt.cat([pt.unsqueeze(r, dim=0) for r in result])
		return out
